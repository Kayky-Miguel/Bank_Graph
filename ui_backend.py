"""Etapa 6 - ponte entre a interface e a recuperacao (Etapa 5).

CONTRATO COM A ETAPA 5
----------------------
A interface procura uma funcao `answer` no modulo `retrieval.py` (ou no que estiver em
BANKGRAPH_RETRIEVER, formato "modulo:funcao"). Assinatura:

    def answer(question: str, ref_date: str = "2026-11-10", limit: int = 25) -> dict

(os parametros extras sao opcionais: a interface so passa os que a funcao aceitar.)

O dict devolvido pode ter as chaves abaixo; todas sao opcionais, exceto "answer":

    {
      "answer": "texto da resposta, gerado SO a partir das evidencias",
      "insufficient_evidence": False,          # True quando o sistema se abstem
      "confidence": "alta" | "media" | "baixa" | 0.0-1.0,
      "confidence_reason": "por que esse nivel",
      "queries": [{"cypher": "...", "params": {...}, "rows": 12, "purpose": "..."}],
      "graph": {"nodes": [...], "relationships": [...]},   # formato de graph_view.collect_graph
      "records": [...],    # alternativa a "graph": Paths/Nodes/Records do driver; a UI monta o subgrafo
      "sources": [{"document_id": "DOC004", "title": "...", "section": "1.2", "page": 5,
                   "text": "trecho", "score": 0.71}],
      "entity_ids": ["C0208", "A0123", "T0001050"],        # destacados no subgrafo
      "rows": [{...}],                                       # tabela de fatos (opcional)
      "notes": ["limitacoes, avisos"],
    }

Enquanto a Etapa 5 nao existir, a interface usa o BaselineRetriever abaixo: templates Cypher
fixos e parametrizados (os mesmos de queries.cypher) + busca vetorial nos documentos. Sem LLM:
a resposta e montada por template, entao serve tambem de linha de base para a Etapa 7.
"""
import importlib
import inspect
import os
import re
import time
import unicodedata
from functools import lru_cache

from graph_view import collect_graph

DEFAULT_REF_DATE = "2026-11-10"    # os dados terminam nessa data
EMBED_MODEL = os.environ.get("EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
# O indice vetorial do Neo4j (cosine) devolve score = (1 + cosseno) / 2: texto SEM relacao ja da ~0,5.
# Calibracao (evaluation/README.md): fora do dominio cos ~0,10; perguntas reais sobre regras cos >= 0,51.
# Corte no meio do caminho: cos 0,30. Confianca "alta" a partir de cos 0,55.
def neo4j_score(cos):
    return (1 + cos) / 2


MIN_VECTOR_SCORE = neo4j_score(0.30)   # 0,65: abaixo disso a busca vetorial nao conta como evidencia
HIGH_VECTOR_SCORE = neo4j_score(0.55)  # 0,775
QUERY_TIMEOUT_S = 15
DISCLAIMER = ("Dados 100% sinteticos. Alertas e transacoes sinalizadas sao sinais simulados "
              "que merecem analise e nao comprovam fraude.")


# ------------------------------------------------------------------ resultado padrao
def normalize_result(raw, question=""):
    """Aceita o dict (ou objeto) da Etapa 5 e devolve o formato completo esperado pela UI."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raw = {k: getattr(raw, k) for k in dir(raw) if not k.startswith("_") and not callable(getattr(raw, k))}
    res = {
        "question": question,
        "answer": str(raw.get("answer") or "").strip(),
        "insufficient_evidence": bool(raw.get("insufficient_evidence", False)),
        "confidence": raw.get("confidence"),
        "confidence_reason": raw.get("confidence_reason", ""),
        "queries": [], "sources": [], "entity_ids": [], "rows": [], "notes": [],
        "graph": {"nodes": [], "relationships": []},
    }
    for q in raw.get("queries") or []:
        q = {"cypher": q} if isinstance(q, str) else dict(q)
        res["queries"].append({"cypher": q.get("cypher", ""), "params": q.get("params") or {},
                               "rows": q.get("rows"), "purpose": q.get("purpose", "")})
    if raw.get("cypher") and not res["queries"]:                 # tolera chave unica "cypher"
        res["queries"].append({"cypher": raw["cypher"], "params": raw.get("params") or {}, "rows": None, "purpose": ""})
    g = raw.get("graph")
    if isinstance(g, dict) and "nodes" in g:
        res["graph"] = {"nodes": list(g.get("nodes") or []), "relationships": list(g.get("relationships") or [])}
    if raw.get("records") is not None:
        collect_graph(raw["records"], graph=res["graph"])
    for s in raw.get("sources") or []:
        s = {"text": s} if isinstance(s, str) else dict(s)
        res["sources"].append(s)
    res["entity_ids"] = [str(x) for x in raw.get("entity_ids") or []]
    res["rows"] = list(raw.get("rows") or [])
    notes = raw.get("notes") or []
    res["notes"] = [notes] if isinstance(notes, str) else list(notes)
    if not res["answer"]:
        res["answer"] = "Nao ha evidencia suficiente para responder."
        res["insufficient_evidence"] = True
    return res


# ------------------------------------------------------------------ descoberta dos backends
def load_external():
    """Retorna (nome, funcao) da Etapa 5, ou (None, motivo) se nao estiver disponivel."""
    spec = os.environ.get("BANKGRAPH_RETRIEVER", "retrieval:answer")
    mod_name, _, fn_name = spec.partition(":")
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError as e:
        if e.name == mod_name:
            return None, f"modulo '{mod_name}' ainda nao existe"
        raise                       # erro de import DENTRO do modulo da Etapa 5: mostrar, nao esconder
    fn = getattr(mod, fn_name or "answer", None)
    if not callable(fn):
        return None, f"'{mod_name}' nao tem a funcao '{fn_name or 'answer'}'"
    return spec, fn


def call_backend(fn, question, **options):
    """Chama fn passando so os parametros que ela aceita; mede latencia; normaliza."""
    try:
        params = inspect.signature(fn).parameters
        accepts_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
        kwargs = {k: v for k, v in options.items() if accepts_kw or k in params}
    except (TypeError, ValueError):
        kwargs = {}
    t0 = time.perf_counter()
    raw = fn(question, **kwargs)
    latency = (time.perf_counter() - t0) * 1000
    res = normalize_result(raw, question)
    res["latency_ms"] = latency
    return res


# ------------------------------------------------------------------ baseline (sem LLM)
def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s)


Q_CUSTOMER = """
MATCH (c:Customer {customer_id: $cid})
OPTIONAL MATCH pa = (c)-[:OWNS]->(:Account)
OPTIONAL MATCH pl = (c)-[:HAS_LOAN]->(:Loan)-[:ON_ACCOUNT]->(:Account)
OPTIONAL MATCH pk = (c)-[:HAS_CARD]->(:Card)
WITH c, collect(DISTINCT pa) AS contas, collect(DISTINCT pl) AS emprestimos, collect(DISTINCT pk) AS cartoes
RETURN c, contas, emprestimos, cartoes,
       [p IN contas | {account_id: nodes(p)[1].account_id, tipo: nodes(p)[1].account_type,
                       status: nodes(p)[1].status, titularidade: relationships(p)[0].ownership_type}] AS contas_info,
       [p IN emprestimos | {loan_id: nodes(p)[1].loan_id, status: nodes(p)[1].status,
                            valor_brl: nodes(p)[1].principal_brl}] AS emprestimos_info,
       [p IN cartoes | {card_id: nodes(p)[1].card_id, bandeira: nodes(p)[1].brand,
                        status: nodes(p)[1].status}] AS cartoes_info
"""

Q_FLAGGED = """
MATCH p = (c:Customer)-[:OWNS]->(a:Account)-[:SENT]->(t:Transaction {flagged: true})
WHERE t.date >= date($ref) - duration({days: $dias})
OPTIONAL MATCH pa = (t)<-[:RAISED_ON]-(:Alert)
OPTIONAL MATCH pl = (c)-[:HAS_LOAN]->(l:Loan {status: 'ACTIVE'})
WITH c, collect(DISTINCT t.transaction_id) AS transacoes, collect(DISTINCT l.loan_id) AS emprestimos_ativos,
     collect(DISTINCT p) + collect(DISTINCT pa) + collect(DISTINCT pl) AS caminhos
RETURN c.customer_id AS cliente, transacoes, emprestimos_ativos, caminhos
ORDER BY cliente LIMIT $limit
"""

Q_INDIRECT = """
MATCH p = (x:Customer)-[:OWNS]->(:Account)<-[:OWNS]-(y:Customer)-[:OWNS]->(:Account)-[:SENT]->(t:Transaction {flagged: true})
WHERE x <> y AND t.date >= date($ref) - duration({days: $dias})
OPTIONAL MATCH pl = (x)-[:HAS_LOAN]->(l:Loan {status: 'ACTIVE'})
WITH x, y, collect(DISTINCT t.transaction_id) AS transacoes, collect(DISTINCT l.loan_id) AS emprestimos_ativos,
     collect(DISTINCT p) + collect(DISTINCT pl) AS caminhos
RETURN x.customer_id AS cliente_indireto, y.customer_id AS via_cliente, transacoes, emprestimos_ativos, caminhos
ORDER BY cliente_indireto LIMIT $limit
"""

Q_JOINT = """
MATCH (c:Customer)-[:OWNS {ownership_type: 'JOINT'}]->(a:Account)
WHERE NOT $com_emprestimo OR EXISTS { (c)-[:HAS_LOAN]->(:Loan {status: 'ACTIVE'}) }
OPTIONAL MATCH po = (a)<-[:OWNS]-(:Customer)
OPTIONAL MATCH pl = (c)-[:HAS_LOAN]->(l:Loan {status: 'ACTIVE'})
WHERE $com_emprestimo
WITH a, collect(DISTINCT c.customer_id) AS clientes, collect(DISTINCT l.loan_id) AS emprestimos_ativos,
     collect(DISTINCT po) + collect(DISTINCT pl) AS caminhos
RETURN a.account_id AS conta, clientes, emprestimos_ativos, caminhos
ORDER BY conta LIMIT $limit
"""

Q_MERCHANT = """
MATCH (c:Customer)-[:OWNS]->(:Account)-[:SENT]->(:Transaction)-[:PAID_TO]->(m:Merchant)
WITH m, count(DISTINCT c) AS clientes
ORDER BY clientes DESC LIMIT $limit
RETURN m.merchant_id AS estabelecimento, m.merchant_name AS nome, m.category AS categoria, clientes,
       COLLECT { MATCH p = (:Customer)-[:OWNS]->(:Account)-[:SENT]->(:Transaction)-[:PAID_TO]->(m)
                 RETURN p LIMIT 3 } AS amostra
"""

Q_TRANSACTION = """
MATCH (t:Transaction {transaction_id: $tid})
OPTIONAL MATCH po = (:Customer)-[:OWNS]->(:Account)-[:SENT]->(t)
OPTIONAL MATCH pm = (t)-[:PAID_TO]->(m:Merchant)
OPTIONAL MATCH pa = (al:Alert)-[:RAISED_ON]->(t)
OPTIONAL MATCH pc = (:Customer)-[:FILED]->(:Complaint)-[:ABOUT]->(t)
RETURN t {.transaction_id, .amount_brl, .transaction_type, .flagged, .scenario, .channel, .status,
          date: toString(t.date)} AS transacao,
       m {.merchant_id, .merchant_name, .category, .risk_profile} AS estabelecimento,
       collect(DISTINCT al {.alert_id, .alert_type, .severity, .note, alert_date: toString(al.alert_date)}) AS alertas,
       collect(DISTINCT po) + collect(DISTINCT pm) + collect(DISTINCT pa) + collect(DISTINCT pc) AS caminhos
"""

Q_DOCS = """
CALL db.index.vector.queryNodes('document_embedding', $k, $vec) YIELD node AS d, score
OPTIONAL MATCH pr = (d)-[:DESCRIBES]->(r:BankingRule)
OPTIONAL MATCH pk = (r)-[:INSTANCE_OF]->(:RuleTopic)-[]->(:Entity)
WITH d, score, collect(DISTINCT r {.rule_id, .rule_name, .description}) AS regras,
     collect(DISTINCT pr) + collect(DISTINCT pk) AS caminhos
RETURN d.document_id AS document_id, d.title AS title, d.section AS section, d.page AS page,
       d.version AS version, d.text AS text, score, regras, caminhos
ORDER BY score DESC
"""


class BaselineRetriever:
    """Roteamento por palavras-chave para templates Cypher fixos (somente leitura, com timeout e LIMIT)."""

    name = "Baseline (templates Cypher + busca vetorial, sem LLM)"

    def __init__(self, driver=None, embed=None):
        self._driver = driver
        self._embed = embed

    # -------- infraestrutura
    @property
    def driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase
            # sem os avisos de "label/propriedade nao existe" a cada consulta: health() explica o problema uma vez
            self._driver = GraphDatabase.driver(
                os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
                notifications_min_severity="OFF")
            self._driver.verify_connectivity()
        return self._driver

    def health(self):
        """Confere se o grafo esta carregado. Retorna (ok, lista de problemas, contagens)."""
        counts = self.run("""RETURN COUNT { (:Customer) } AS customers, COUNT { (:Document) } AS documents,
                                    COUNT { (d:Document) WHERE d.embedding IS NOT NULL } AS embedded,
                                    COUNT { (:Entity) } AS entities,
                                    COUNT { (c:Customer) WHERE c.pagerank IS NOT NULL } AS ranked""", {})[0]
        idx = {r["name"] for r in self.run("SHOW INDEXES YIELD name RETURN name", {})}
        counts = dict(counts)
        problems = []
        if counts["customers"] == 0:
            problems.append("o grafo esta vazio: rode `python ingest.py --data ./BankGraph_AI_Dataset`")
        if "document_embedding" not in idx or counts["embedded"] == 0:
            problems.append("faltam os embeddings/indice vetorial: rode `python embed_docs.py`")
        if counts["entities"] == 0:
            problems.append("faltam as entidades extraidas (KAG): rode `python extract_entities.py "
                            "--data ./BankGraph_AI_Dataset --from-results`")
        if counts["ranked"] == 0:
            problems.append("faltam os algoritmos de grafo (PageRank/comunidades): rode `python graph_algorithms.py`")
        return not problems, problems, counts

    def embed(self, text):
        if self._embed is None:
            self._embed = _sentence_model()
        return self._embed(text)

    def run(self, cypher, params):
        """Transacao SOMENTE LEITURA com timeout (o servidor recusa escrita e aborta consultas lentas)."""
        from neo4j import READ_ACCESS, unit_of_work

        @unit_of_work(timeout=QUERY_TIMEOUT_S)
        def work(tx):
            return list(tx.run(cypher, params))

        with self.driver.session(default_access_mode=READ_ACCESS) as s:
            return s.execute_read(work)

    # -------- roteamento
    def route(self, question):
        q = _norm(question)
        cid = re.search(r"\bc\d{4}\b", q)
        tid = re.search(r"\bt\d{7}\b", q)
        dias = re.search(r"(\d+)\s*dias", q)
        if tid:
            return "transacao", {"tid": tid.group(0).upper()}
        if cid:
            return "cliente", {"cid": cid.group(0).upper()}
        if re.search(r"sinaliz|alerta|suspeit", q) and "fraude" not in q:
            if re.search(r"indiret|conjunt|compartilh", q):
                return "indireta", {"dias": int(dias.group(1)) if dias else 365}
            return "sinalizadas", {"dias": int(dias.group(1)) if dias else 30}
        if re.search(r"conjunt|compartilh", q):
            return "conjunta", {"com_emprestimo": "emprestimo" in q}
        if re.search(r"estabelecimento|comerciante|merchant", q) and re.search(r"concentr|mesmo|varios|mais clientes", q):
            return "estabelecimentos", {}
        return "documentos", {}

    def answer(self, question, ref_date=DEFAULT_REF_DATE, limit=25, k=5):
        intent, p = self.route(question)
        handler = getattr(self, f"_{intent}")
        res = handler(question, dict(p, ref=ref_date, limit=int(limit), k=int(k)))
        res.setdefault("notes", []).append(f"Intencao detectada pelo baseline: {intent}.")
        if "fraude" in _norm(question):
            res["notes"].insert(0, "Os dados nao permitem afirmar fraude: " + DISCLAIMER)
        return res

    # -------- handlers
    def _query(self, cypher, params, purpose):
        recs = self.run(cypher, params)
        shown = {k: v for k, v in params.items() if k != "vec"}
        if "vec" in params:
            shown["vec"] = f"<embedding da pergunta, {len(params['vec'])} dim>"
        return recs, {"cypher": cypher.strip(), "params": shown, "rows": len(recs), "purpose": purpose}

    def _cliente(self, question, p):
        recs, q = self._query(Q_CUSTOMER, {"cid": p["cid"]}, "Contas, emprestimos e cartoes do cliente")
        if not recs:
            return {"answer": f"O cliente {p['cid']} nao existe no grafo.", "insufficient_evidence": True,
                    "confidence": "alta", "queries": [q]}
        r = recs[0]
        contas, emps, cards = r["contas_info"], r["emprestimos_info"], r["cartoes_info"]
        ativos = [e for e in emps if e["status"] == "ACTIVE"]
        nq = _norm(question)
        foco = ("emprestimos" if "emprestimo" in nq else "cartoes" if "cartao" in nq or "cartoes" in nq
                else "contas")
        so_ativos = foco == "emprestimos" and "ativo" in nq
        frases = {
            "contas": f"{len(contas)} conta(s): " + ", ".join(
                f"{c['account_id']} ({c['tipo']}, {c['titularidade']}, {c['status']})" for c in contas) + ".",
            "emprestimos": f"Emprestimos: {len(emps)} no total, {len(ativos)} ativo(s)" + (": " + ", ".join(
                f"{e['loan_id']} (R$ {(e['valor_brl'] or 0):,.2f})" for e in ativos) if ativos else "") + ".",
            "cartoes": f"Cartoes: {len(cards)}" + (": " + ", ".join(
                f"{k['card_id']} ({k['bandeira']}, {k['status']})" for k in cards) if cards else "") + ".",
        }
        ordem = [foco] + [f for f in frases if f != foco]          # a parte perguntada vem primeiro
        txt = [f"**{p['cid']}** ({r['c']['name']}, segmento {r['c']['segment']})."] + [frases[f] for f in ordem]
        if foco == "contas":
            ids, rows = [p["cid"]] + [c["account_id"] for c in contas], contas
        elif foco == "cartoes":
            ids, rows = [p["cid"]] + [k["card_id"] for k in cards], cards
        else:
            sel = ativos if so_ativos else emps
            ids, rows = [p["cid"]] + [e["loan_id"] for e in sel], sel
        return {"answer": " ".join(txt), "confidence": "alta", "confidence_reason": "consulta estruturada direta",
                "queries": [q], "records": recs, "entity_ids": ids, "rows": rows}

    def _sinalizadas(self, question, p):
        params = {"ref": p["ref"], "dias": p["dias"], "limit": p["limit"]}
        recs, q = self._query(Q_FLAGGED, params, "Clientes donos de contas com transacao sinalizada na janela")
        rows = [{"cliente": r["cliente"], "transacoes": r["transacoes"], "emprestimos_ativos": r["emprestimos_ativos"]} for r in recs]
        if not rows:
            return {"answer": f"Nenhuma transacao sinalizada nos {p['dias']} dias anteriores a {p['ref']}.",
                    "insufficient_evidence": True, "confidence": "alta", "queries": [q]}
        com = [r["cliente"] for r in rows if r["emprestimos_ativos"]]
        ans = (f"{len(rows)} cliente(s) sao donos de contas com transacao **sinalizada** nos {p['dias']} dias "
               f"ate {p['ref']}: {', '.join(r['cliente'] for r in rows)}. "
               f"Desses, {len(com)} tem emprestimo ativo" + (f": {', '.join(com)}." if com else "."))
        ids = [r["cliente"] for r in rows] + [t for r in rows for t in r["transacoes"]] + [l for r in rows for l in r["emprestimos_ativos"]]
        return {"answer": ans, "confidence": "alta", "confidence_reason": "consulta estruturada multi-hop",
                "queries": [q], "records": [r["caminhos"] for r in recs], "rows": rows, "entity_ids": ids,
                "notes": [DISCLAIMER] + (["Resultado truncado pelo LIMIT."] if len(rows) >= p["limit"] else [])}

    def _indireta(self, question, p):
        params = {"ref": p["ref"], "dias": p["dias"], "limit": p["limit"]}
        recs, q = self._query(Q_INDIRECT, params, "Relacao indireta via conta conjunta com dono de conta sinalizada")
        rows = [{"cliente_indireto": r["cliente_indireto"], "via_cliente": r["via_cliente"],
                 "transacoes": r["transacoes"], "emprestimos_ativos": r["emprestimos_ativos"]} for r in recs]
        if not rows:
            return {"answer": f"Nenhuma relacao indireta encontrada em {p['dias']} dias. Tente uma janela maior.",
                    "insufficient_evidence": True, "confidence": "media", "queries": [q]}
        ans = (f"{len({r['cliente_indireto'] for r in rows})} cliente(s) dividem conta conjunta com alguem que e dono de conta "
               f"com transacao sinalizada (janela de {p['dias']} dias): " +
               "; ".join(f"{r['cliente_indireto']} via {r['via_cliente']}" for r in rows) + ".")
        ids = [r["cliente_indireto"] for r in rows] + [r["via_cliente"] for r in rows]
        return {"answer": ans, "confidence": "alta", "confidence_reason": "caminho multi-hop explicito no grafo",
                "queries": [q], "records": [r["caminhos"] for r in recs], "rows": rows, "entity_ids": ids,
                "notes": [DISCLAIMER, "Relacao indireta nao implica participacao do cliente."]}

    def _conjunta(self, question, p):
        params = {"com_emprestimo": p["com_emprestimo"], "limit": p["limit"]}
        recs, q = self._query(Q_JOINT, params, "Contas conjuntas e seus titulares")
        rows = [{"conta": r["conta"], "clientes": r["clientes"], "emprestimos_ativos": r["emprestimos_ativos"]} for r in recs]
        if not rows:
            return {"answer": "Nenhuma conta conjunta atende ao criterio.", "insufficient_evidence": True,
                    "confidence": "alta", "queries": [q]}
        clientes = sorted({c for r in rows for c in r["clientes"]})
        filtro = " e emprestimo ativo" if p["com_emprestimo"] else ""
        ans = (f"{len(clientes)} cliente(s) com conta conjunta{filtro} em {len(rows)} conta(s)"
               f"{' (limitado a ' + str(p['limit']) + ' contas)' if len(rows) >= p['limit'] else ''}: {', '.join(clientes)}.")
        return {"answer": ans, "confidence": "alta", "confidence_reason": "consulta estruturada",
                "queries": [q], "records": [r["caminhos"] for r in recs], "rows": rows, "entity_ids": clientes}

    def _estabelecimentos(self, question, p):
        recs, q = self._query(Q_MERCHANT, {"limit": min(p["limit"], 10)}, "Estabelecimentos por numero de clientes distintos")
        rows = [{k: r[k] for k in ("estabelecimento", "nome", "categoria", "clientes")} for r in recs]
        if not rows:
            return {"answer": "Sem transacoes no grafo.", "insufficient_evidence": True, "queries": [q]}
        top = rows[0]
        ans = (f"O estabelecimento que mais concentra pagamentos e **{top['nome']}** ({top['estabelecimento']}), "
               f"com {top['clientes']} clientes distintos. Seguem: " +
               ", ".join(f"{r['nome']} ({r['clientes']})" for r in rows[1:5]) + ".")
        return {"answer": ans, "confidence": "alta", "confidence_reason": "agregacao estruturada",
                "queries": [q], "records": [r["amostra"] for r in recs[:5]], "rows": rows,
                "entity_ids": [r["estabelecimento"] for r in rows],
                "notes": ["O subgrafo mostra so 3 caminhos de exemplo por estabelecimento (top 5)."]}

    def _transacao(self, question, p):
        recs, q = self._query(Q_TRANSACTION, {"tid": p["tid"]}, "Evidencias ligadas a transacao")
        if not recs or recs[0]["transacao"] is None:
            return {"answer": f"A transacao {p['tid']} nao existe no grafo.", "insufficient_evidence": True,
                    "confidence": "alta", "queries": [q]}
        r = recs[0]
        t, m, als = r["transacao"], r["estabelecimento"] or {}, r["alertas"]
        partes = [f"Transacao {t['transaction_id']}: R$ {t['amount_brl']:,.2f}, {t['transaction_type']} em {t['date']}, "
                  f"cenario simulado `{t['scenario']}`, sinalizada = {t['flagged']}."]
        if m:
            partes.append(f"Destino: {m.get('merchant_name')} ({m.get('category')}, perfil de risco {m.get('risk_profile')}).")
        if als:
            partes.append("Alertas: " + "; ".join(f"{a['alert_type']} (severidade {a['severity']}, {a['alert_date']})" for a in als) + ".")
        elif t["flagged"]:
            partes.append("Nenhum alerta registrado explica a sinalizacao.")
        return {"answer": " ".join(partes), "confidence": "alta", "confidence_reason": "fatos diretos do grafo",
                "queries": [q], "records": [r["caminhos"]], "rows": [t] + als,
                "entity_ids": [t["transaction_id"]] + [a["alert_id"] for a in als], "notes": [DISCLAIMER]}

    def _documentos(self, question, p):
        vec = self.embed(question)
        recs, q = self._query(Q_DOCS, {"k": p["k"], "vec": vec}, "Busca vetorial nos documentos + regras ligadas (KAG)")
        sources = [{"document_id": r["document_id"], "title": r["title"], "section": r["section"], "page": r["page"],
                    "version": r["version"], "text": r["text"], "score": round(r["score"], 3)} for r in recs]
        good = [r for r in recs if r["score"] >= MIN_VECTOR_SCORE]
        if not good:
            return {"answer": "Nao encontrei documento suficientemente relacionado a pergunta no acervo (fora do dominio "
                              "ou sem evidencia).", "insufficient_evidence": True, "confidence": "baixa",
                    "confidence_reason": f"maior similaridade {max((s['score'] for s in sources), default=0):.2f} < {MIN_VECTOR_SCORE:.2f}",
                    "queries": [q], "sources": sources}
        regras, vistos = [], set()
        for r in good:
            for rg in r["regras"]:
                if rg["rule_id"] not in vistos:
                    vistos.add(rg["rule_id"])
                    regras.append((rg, r["document_id"]))
        top = good[0]["score"]
        linhas = [f"- **{rg['rule_name']}** ({rg['rule_id']}, fonte {doc}): {rg['description']}" for rg, doc in regras[:6]]
        ans = "Regras documentadas mais relacionadas a pergunta:\n" + "\n".join(linhas) if linhas else \
              "Documentos relacionados foram encontrados, mas sem regra estruturada associada. Veja as fontes."
        conf = "alta" if top >= HIGH_VECTOR_SCORE else "media"
        return {"answer": ans, "confidence": conf, "confidence_reason": f"similaridade vetorial maxima {top:.2f}",
                "queries": [q], "records": [r["caminhos"] for r in good], "sources": sources,
                "rows": [rg for rg, _ in regras], "entity_ids": [r["document_id"] for r in good] + [rg["rule_id"] for rg, _ in regras]}


@lru_cache(maxsize=1)
def _sentence_model():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(EMBED_MODEL)
    return lambda text: m.encode(text, normalize_embeddings=True).tolist()
