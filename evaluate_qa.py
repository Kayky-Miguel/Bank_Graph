"""Etapa 7 - avaliacao das respostas (perguntas -> recuperacao -> resposta).

O gabarito de cada pergunta e CALCULADO DIRETO DOS CSVs com pandas, sem passar pelo Neo4j nem pelo
codigo avaliado. Assim, um erro de modelagem/ingestao/consulta aparece como erro na avaliacao.

Uso (variaveis NEO4J_* definidas, grafo carregado e embeddings gerados):
  python evaluate_qa.py                                  # baseline + vetorial isolada (comparacao)
  python evaluate_qa.py --backends baseline retrieval    # inclui a Etapa 5 (retrieval.py:answer)
  python evaluate_qa.py --gold-only                      # so imprime o gabarito (nao precisa de Neo4j)
Saida: evaluation/results_<backend>.json e evaluation/report.md

Metricas por pergunta
  ids        precisao/recall/F1 dos IDs esperados (so do tipo pedido: C, A, L, CC, T, AL, M, R...)
  topico     acerto@k: algum documento/regra das k primeiras fontes e do tema esperado
  abstencao  nas perguntas sem resposta / ambiguas / fora do dominio, o sistema deve se abster
  frase      a resposta deve conter (ou nao conter) um padrao (ex.: "nao comprova fraude")
  sem_suporte IDs citados no texto da resposta que nao aparecem nas evidencias (proxy de alucinacao)
"""
import argparse
import json
import os
import re
import statistics
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "BankGraph_AI_Dataset"
OUT = ROOT / "evaluation"
REF = date(2026, 11, 10)                       # mesma data de referencia fixa da interface
ID_RE = re.compile(r"\b(?:CC\d{4}|CP\d{5}|AL\d{5}|DOC\d{3}|C\d{4}|A\d{4}|T\d{7}|L\d{4}|M\d{4}|B\d{3}|E\d{4}|R\d{3})\b")
ID_PREFIX = {"customer": r"C\d{4}", "account": r"A\d{4}", "loan": r"L\d{4}", "card": r"CC\d{4}",
             "transaction": r"T\d{7}", "alert": r"AL\d{5}", "merchant": r"M\d{4}", "rule": r"R\d{3}"}
RECALL_OK = 0.8                                # recall minimo para considerar a pergunta correta


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s)


# ------------------------------------------------------------------ dados
def load_data(path=DATA):
    names = ["customers", "accounts", "account_owners", "transactions", "cards", "loans", "merchants",
             "alerts", "banking_rules", "documents"]
    d = {n: pd.read_csv(Path(path) / f"{n}.csv", encoding="utf-8-sig", dtype=str, keep_default_na=False) for n in names}
    d["transactions"]["date"] = pd.to_datetime(d["transactions"]["transaction_date"]).dt.date
    return d


def flagged_owners(d, days):
    t = d["transactions"]
    t = t[(t.flagged == "True") & (t.date >= REF - timedelta(days=days))]
    return t.merge(d["account_owners"], on="account_id")      # cliente x conta x transacao sinalizada


def active_loans(d, customers=None):
    lo = d["loans"][d["loans"].status == "ACTIVE"]
    return lo if customers is None else lo[lo.customer_id.isin(customers)]


def topic_rules(d, topic):
    r = d["banking_rules"]
    return set(r[r.rule_name.map(norm) == norm(topic)].rule_id)


# ------------------------------------------------------------------ perguntas + gabarito
def gold_central(d, days=30):
    fo = flagged_owners(d, days)
    custs = set(fo.customer_id)
    return custs | set(active_loans(d, custs).loan_id)


def gold_indirect(d, days):
    """x divide uma conta com y, e y e dono de OUTRA conta com transacao sinalizada.
    Se a conta sinalizada for a propria conta compartilhada, a relacao de x e direta, nao indireta
    (no Cypher o caminho nao pode reusar o mesmo OWNS de y)."""
    own = d["account_owners"]
    pairs = own.merge(own, on="account_id")                  # x e y donos da mesma conta
    pairs = pairs[pairs.customer_id_x != pairs.customer_id_y]
    fo = flagged_owners(d, days)[["customer_id", "account_id"]].rename(
        columns={"customer_id": "customer_id_y", "account_id": "flagged_account"})
    m = pairs.merge(fo, on="customer_id_y")
    return set(m[m.flagged_account != m.account_id].customer_id_x)


def gold_merchant_top(d, k=5):
    t = d["transactions"].merge(d["account_owners"], on="account_id")
    s = t.groupby("merchant_id").customer_id.nunique().sort_values(ascending=False)
    return set(s.head(k).index)


def gold_joint(d, with_loan=False):
    j = d["account_owners"][d["account_owners"].ownership_type == "JOINT"]
    c = set(j.customer_id)
    return c & set(active_loans(d).customer_id) if with_loan else c


def gold_loan_rules(d, cid):
    if not (d["loans"].customer_id == cid).any():
        return set()
    r = d["banking_rules"]
    return set(r[(r.rule_name.map(norm) == norm("Empréstimo Pessoal")) & (r.is_active == "True")].rule_id)


def gold_shortest_path_accounts(d, a, b):
    """Contas no(s) caminho(s) minimo(s) entre dois clientes na rede Cliente-Conta-Transacao-Estabelecimento."""
    import networkx as nx
    g = nx.Graph()
    g.add_edges_from(zip(d["account_owners"].customer_id, d["account_owners"].account_id))
    t = d["transactions"]
    g.add_edges_from(zip(t.account_id, t.transaction_id))
    g.add_edges_from(zip(t.transaction_id, t.merchant_id))
    return {n for p in nx.all_shortest_paths(g, a, b) for n in p if re.fullmatch(r"A\d{4}", n)}


def gold_pagerank_top(d, k=5):
    from graph_algorithms import compute, load_from_csv
    res = compute(*load_from_csv(DATA))
    g, pr = res["graph"], res["pagerank"]
    return set(sorted((n for n in g if g.nodes[n]["kind"] == "merchant"), key=lambda n: -pr[n])[:k])


def _own(d, cid):
    return set(d["account_owners"][d["account_owners"].customer_id == cid].account_id)


QUESTIONS = [
    # ---- basicas
    dict(id="B01", difficulty="basica", kind="answerable", question="Quais contas pertencem ao cliente C0208?",
         expect="account", gold=lambda d: _own(d, "C0208")),
    dict(id="B02", difficulty="basica", kind="answerable", question="Quais empréstimos do cliente C0208 estão ativos?",
         expect="loan", gold=lambda d: set(active_loans(d, {"C0208"}).loan_id)),
    dict(id="B03", difficulty="basica", kind="answerable", question="Quais contas pertencem ao cliente C0001?",
         expect="account", gold=lambda d: _own(d, "C0001")),
    dict(id="B04", difficulty="basica", kind="answerable", question="Quais cartões o cliente C0352 possui?",
         expect="card", gold=lambda d: set(d["cards"][d["cards"].customer_id == "C0352"].card_id)),
    dict(id="B05", difficulty="basica", kind="answerable", question="Por quais evidências a transação T0001050 foi sinalizada?",
         expect="alert", gold=lambda d: set(d["alerts"][d["alerts"].transaction_id == "T0001050"].alert_id)),
    # ---- intermediarias
    dict(id="I01", difficulty="intermediaria", kind="answerable", question="Quais clientes possuem contas conjuntas?",
         expect="customer", gold=lambda d: gold_joint(d), case="Q001"),
    dict(id="I02", difficulty="intermediaria", kind="answerable", question="Quais clientes têm conta conjunta e empréstimo ativo?",
         expect="customer", gold=lambda d: gold_joint(d, with_loan=True)),
    dict(id="I03", difficulty="intermediaria", kind="answerable", question="Quais estabelecimentos concentram pagamentos de vários clientes?",
         expect="merchant", gold=lambda d: gold_merchant_top(d, 5), case="Q003",
         note="gabarito = top 5 por clientes distintos"),
    dict(id="I04", difficulty="intermediaria", kind="answerable",
         question="Quais clientes têm empréstimos ativos e alertas simulados nos últimos 30 dias?",
         expect="customer", gold=lambda d: set(active_loans(d, set(flagged_owners(d, 30).customer_id)).customer_id), case="Q002"),
    dict(id="I05", difficulty="intermediaria", kind="answerable", question="Quais clientes pagaram ao estabelecimento M0007?",
         expect="customer", gold=lambda d: set(d["transactions"][d["transactions"].merchant_id == "M0007"]
                                               .merge(d["account_owners"], on="account_id").customer_id)),
    # ---- avancadas
    dict(id="A01", difficulty="avancada", kind="answerable",
         question="Quais clientes possuem relacionamento com contas que realizaram transações sinalizadas nos últimos "
                  "30 dias e, entre eles, quais possuem empréstimos ativos?",
         expect=["customer", "loan"], gold=lambda d: gold_central(d, 30), note="pergunta central da apresentacao"),
    dict(id="A02", difficulty="avancada", kind="answerable",
         question="Quais clientes têm relação indireta, por conta conjunta, com contas que tiveram transações "
                  "sinalizadas nos últimos 365 dias?",
         expect="customer", gold=lambda d: gold_indirect(d, 365)),
    dict(id="A03", difficulty="avancada", kind="answerable", question="Quais regras documentadas se aplicam ao empréstimo do cliente C0208?",
         expect="rule", gold=lambda d: gold_loan_rules(d, "C0208"), topic="Empréstimo Pessoal",
         note="ingest.py liga todo Loan as regras ATIVAS 'Empréstimo Pessoal' (FOLLOWS)"),
    dict(id="A04", difficulty="avancada", kind="answerable", question="Quais regras orientam a revisão de transferências recorrentes?",
         expect="rule", gold=lambda d: topic_rules(d, "Frequência de Transferências"), topic="Frequência de Transferências", case="Q004"),
    dict(id="A05", difficulty="avancada", kind="answerable", question="Qual é o limite do PIX para o segmento BASIC?",
         expect="rule", gold=lambda d: topic_rules(d, "Limite de Transferência PIX"), topic="Limite de Transferência PIX",
         must_say=r"2\.?000"),
    dict(id="A06", difficulty="avancada", kind="answerable", question="O que acontece quando há concentração de pagamentos em um estabelecimento?",
         expect="rule", gold=lambda d: topic_rules(d, "Concentração de Pagamentos"), topic="Concentração de Pagamentos"),
    # ---- algoritmos de grafo
    dict(id="A07", difficulty="avancada", kind="answerable",
         question="Como o cliente C0249 se conecta ao cliente C0306 no grafo?",
         expect="account", gold=lambda d: gold_shortest_path_accounts(d, "C0249", "C0306"),
         note="caminho minimo (shortestPath); gabarito por busca em largura nos CSVs"),
    dict(id="A08", difficulty="avancada", kind="answerable",
         question="Quais estabelecimentos são mais centrais na rede de pagamentos (PageRank)?",
         expect="merchant", gold=lambda d: gold_pagerank_top(d, 5),
         note="gabarito = top 5 do PageRank calculado a partir dos CSVs (requer graph_algorithms.py gravado no grafo)"),
    # ---- sem resposta
    dict(id="U01", difficulty="avancada", kind="unanswerable", question="Um alerta permite afirmar que houve fraude?",
         must_say=r"nao (comprova|permite|permitem)", case="Q005"),
    dict(id="U02", difficulty="basica", kind="unanswerable", question="Quais contas pertencem ao cliente C9999?"),
    dict(id="U03", difficulty="basica", kind="unanswerable", question="Qual é o CPF do cliente C0001?",
         must_not=r"\d{3}\.\d{3}\.\d{3}-\d{2}"),
    # ---- ambiguas
    dict(id="M01", difficulty="basica", kind="ambiguous", question="Quais contas pertencem ao cliente?"),
    dict(id="M02", difficulty="intermediaria", kind="ambiguous", question="E os empréstimos dele, estão ativos?"),
    # ---- fora do dominio
    dict(id="O01", difficulty="basica", kind="out_of_domain", question="Qual a previsão do tempo para amanhã em Maceió?"),
    dict(id="O02", difficulty="basica", kind="out_of_domain", question="Qual é a capital da França?"),
]


def build_gold(d):
    # cada regra existe em 3 copias identicas (uma por versao do documento): R001 = R011 = R021.
    # Perguntas sobre regras sao avaliadas por TEMA; citar qualquer copia do tema certo conta como acerto.
    r = d["banking_rules"]
    rule_topic = dict(zip(r.rule_id, r.rule_name.map(norm)))
    out = {}
    for q in QUESTIONS:
        g = dict(q)
        g["gold_ids"] = sorted(q["gold"](d)) if "gold" in q else []
        g.pop("gold", None)
        if "rule" in _types(q.get("expect")):
            g["rule_topic"] = rule_topic
        out[q["id"]] = g
    return out


# ------------------------------------------------------------------ metricas
def _types(expect):
    return [expect] if isinstance(expect, str) else list(expect or [])


def _of_types(ids, types):
    pats = [re.compile(rf"^{ID_PREFIX[t]}$") for t in types]
    return {i for i in ids if any(p.match(i) for p in pats)}


def evidence_ids(res):
    """IDs que aparecem nas evidencias (nos do subgrafo, linhas recuperadas, fontes)."""
    blob = json.dumps({"g": res.get("graph"), "r": res.get("rows"), "s": res.get("sources")}, ensure_ascii=False, default=str)
    return set(ID_RE.findall(blob))


def score(q, res, rules_topic=None):
    """Compara um resultado normalizado (ui_backend.normalize_result) com o gabarito da pergunta."""
    text = res["answer"] + " " + " ".join(res.get("notes") or [])
    answer_ids = set(ID_RE.findall(res["answer"]))
    m = {"id": q["id"], "kind": q["kind"], "difficulty": q["difficulty"], "error": res.get("error"),
         "latency_ms": res.get("latency_ms"), "abstained": bool(res.get("insufficient_evidence")),
         "has_evidence": bool(res["graph"]["nodes"] or res["sources"] or res["rows"])}
    m["unsupported_ids"] = sorted(answer_ids - evidence_ids(res) - {q["question"]} -
                                  set(ID_RE.findall(q["question"])))
    checks = []
    if q["kind"] == "answerable":
        types = _types(q.get("expect"))
        gold = set(q["gold_ids"])
        pred = _of_types(set(res.get("entity_ids") or []) | answer_ids, types)
        if q.get("rule_topic"):                       # regras: compara temas, nao copias
            rt = q["rule_topic"]
            gold = {rt.get(i, i) for i in gold}
            pred = {rt.get(i, i) for i in pred}
        tp = len(gold & pred)
        p = tp / len(pred) if pred else 0.0
        r = tp / len(gold) if gold else (1.0 if not pred else 0.0)
        m.update(precision=round(p, 3), recall=round(r, 3), f1=round(2 * p * r / (p + r), 3) if p + r else 0.0,
                 n_gold=len(gold), n_pred=len(pred), missing=sorted(gold - pred)[:15], extra=sorted(pred - gold)[:15])
        checks.append(r >= RECALL_OK and not m["abstained"])
        if q.get("topic"):
            want = norm(q["topic"])
            titles = [norm(re.sub(r"\s*-\s*Documento\s*\d+\s*$", "", s.get("title", ""))) for s in res["sources"][:3]]
            m["topic_hit@3"] = want in titles if res["sources"] else None
    else:
        ok = m["abstained"]
        if q.get("must_say"):
            ok = ok or bool(re.search(q["must_say"], norm(text)))
        checks.append(ok)
        m["abstention_ok"] = ok
    if q.get("must_say"):
        m["must_say_ok"] = bool(re.search(q["must_say"], norm(text)))
        checks.append(m["must_say_ok"])
    if q.get("must_not"):
        m["must_not_ok"] = not re.search(q["must_not"], text)
        checks.append(m["must_not_ok"])
    m["correct"] = all(checks) and not m["error"]
    return m


def summarize(scores):
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.mean(xs), 3) if xs else None
    ans = [s for s in scores if s["kind"] == "answerable"]
    non = [s for s in scores if s["kind"] != "answerable"]
    lat = [s["latency_ms"] for s in scores if s.get("latency_ms") is not None and not s["error"]]
    return {
        "perguntas": len(scores),
        "acuracia": mean([float(s["correct"]) for s in scores]),
        "acuracia_respondiveis": mean([float(s["correct"]) for s in ans]),
        "precisao_ids": mean([s.get("precision") for s in ans]),
        "recall_ids": mean([s.get("recall") for s in ans]),
        "f1_ids": mean([s.get("f1") for s in ans]),
        "topico_hit@3": mean([float(s["topic_hit@3"]) for s in ans if s.get("topic_hit@3") is not None]),
        "abstencao_correta": mean([float(s["abstention_ok"]) for s in non]),
        "abstencao_indevida": mean([float(s["abstained"]) for s in ans]),
        "respostas_com_evidencia": mean([float(s["has_evidence"]) for s in scores if not s["abstained"]]),
        "respostas_com_id_sem_suporte": mean([float(bool(s["unsupported_ids"])) for s in scores]),
        "erros": sum(1 for s in scores if s["error"]),
        "latencia_media_ms": round(statistics.mean(lat)) if lat else None,
        "latencia_p95_ms": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)]) if lat else None,
    }


# ------------------------------------------------------------------ backends
class VectorOnlyRetriever:
    """Linha de base SEM grafo: so busca vetorial em documentos e regras, nenhuma travessia/Cypher estruturado."""

    name = "Vetorial isolada (sem grafo)"

    def __init__(self, base):
        self.base = base             # reaproveita conexao e modelo de embeddings do baseline

    def answer(self, question, k=5, **_):
        from ui_backend import MIN_VECTOR_SCORE
        vec = self.base.embed(question)
        docs = self.base.run("""CALL db.index.vector.queryNodes('document_embedding', $k, $vec) YIELD node AS d, score
                                RETURN d.document_id AS document_id, d.title AS title, d.section AS section,
                                       d.page AS page, d.text AS text, score""", {"k": k, "vec": vec})
        rules = self.base.run("""CALL db.index.vector.queryNodes('rule_embedding', $k, $vec) YIELD node AS r, score
                                 RETURN r.rule_id AS rule_id, r.rule_name AS rule_name, r.description AS description, score""",
                              {"k": k, "vec": vec})
        sources = [dict(r) for r in docs]
        rows = [dict(r) for r in rules if r["score"] >= MIN_VECTOR_SCORE]
        if not rows and not any(s["score"] >= MIN_VECTOR_SCORE for s in sources):
            return {"answer": "Sem evidencia suficiente nos documentos.", "insufficient_evidence": True,
                    "sources": sources, "confidence": "baixa"}
        ans = "\n".join(f"- {r['rule_name']} ({r['rule_id']}): {r['description']}" for r in rows) or sources[0]["text"]
        return {"answer": ans, "sources": sources, "rows": rows, "entity_ids": [r["rule_id"] for r in rows],
                "queries": [{"cypher": "vector search (document_embedding, rule_embedding)", "params": {"k": k}}]}


def make_backends(names):
    from ui_backend import BaselineRetriever, load_external
    base = BaselineRetriever()
    out = {}
    for n in names:
        if n == "baseline":
            out[n] = base.answer
        elif n == "vector":
            out[n] = VectorOnlyRetriever(base).answer
        elif n == "retrieval":
            spec, fn = load_external()
            if spec is None:
                raise SystemExit(f"Etapa 5 indisponivel: {fn}")
            import retrieval
            print(f"Etapa 5: LLM = {retrieval.PROVIDER}" + ("  (ATENCAO: respostas simuladas, sem valor de avaliacao; "
                  "defina OPENAI_API_KEY)" if retrieval.PROVIDER == "mock" else f", modelo {retrieval.G.LLM_MODEL}"))
            out[n] = fn
        else:
            raise SystemExit(f"backend desconhecido: {n}")
    missing = [v for v in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD") if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"Variaveis nao definidas neste terminal: {', '.join(missing)}.\n"
                         "Defina-as na MESMA janela (ex.: $env:NEO4J_URI=\"neo4j://127.0.0.1:7687\") e ative o .venv.")
    ok, problems, counts = base.health()
    print(f"Neo4j em {os.environ.get('NEO4J_URI')}: {counts['customers']} clientes, {counts['documents']} documentos "
          f"({counts['embedded']} com embedding), {counts['entities']} entidades extraidas, "
          f"{counts.get('ranked', 0)} clientes com PageRank")
    if not ok:
        raise SystemExit("O grafo nao esta pronto para a avaliacao:\n  - " + "\n  - ".join(problems) +
                         "\nConfira se a instancia ligada no Neo4j Desktop e a mesma em que voce carregou os dados.")
    if "baseline" in names or "vector" in names:
        base.embed("aquecimento")    # carrega o modelo antes de medir latencia
    return out


def run_backend(fn, gold, ref_date="2026-11-10", limit=100):
    from ui_backend import call_backend
    scores, raw = [], {}
    for qid, q in gold.items():
        try:
            res = call_backend(fn, q["question"], ref_date=ref_date, limit=limit)
        except Exception as e:                     # uma falha nao derruba a avaliacao inteira
            res = {"answer": "", "insufficient_evidence": False, "graph": {"nodes": [], "relationships": []},
                   "sources": [], "rows": [], "notes": [], "entity_ids": [], "error": f"{type(e).__name__}: {e}"}
        s = score(q, res)
        scores.append(s)
        raw[qid] = {"question": q["question"], "answer": res["answer"], "abstained": res.get("insufficient_evidence"),
                    "entity_ids": res.get("entity_ids"), "queries": res.get("queries"), "error": res.get("error"),
                    "n_nodes": len(res["graph"]["nodes"]), "sources": [s_.get("document_id") for s_ in res["sources"]],
                    "rows_sample": res["rows"][:8], "notes": res.get("notes")}
        flag = "OK  " if s["correct"] else ("ERRO" if s["error"] else "FALHA")
        print(f"  {flag} {qid} {q['question'][:70]}")
        if s["error"]:
            print(f"       {s['error'][:200]}")
    return scores, raw


# ------------------------------------------------------------------ relatorio
LABELS = [("acuracia", "Acuracia geral"), ("acuracia_respondiveis", "Acuracia (respondiveis)"),
          ("precisao_ids", "Precisao dos IDs"), ("recall_ids", "Recall dos IDs"), ("f1_ids", "F1 dos IDs"),
          ("topico_hit@3", "Tema correto nas 3 primeiras fontes"), ("abstencao_correta", "Abstencao correta (sem resposta/ambigua/fora)"),
          ("abstencao_indevida", "Abstencao indevida (respondiveis)"), ("respostas_com_evidencia", "Respostas com evidencia rastreavel"),
          ("respostas_com_id_sem_suporte", "Respostas com ID sem suporte"), ("erros", "Erros de execucao"),
          ("latencia_media_ms", "Latencia media (ms)"), ("latencia_p95_ms", "Latencia p95 (ms)")]


def fmt(v):
    return "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def report(gold, results):
    names = list(results)
    lines = ["# Avaliacao das respostas - BankGraph AI", "",
             f"Gerado em {time.strftime('%Y-%m-%d %H:%M')}. Data de referencia dos dados: {REF}. "
             f"{len(gold)} perguntas; gabarito calculado direto dos CSVs (evaluate_qa.py).", "",
             "## Resumo", "", "| Metrica | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for key, label in LABELS:
        lines.append(f"| {label} | " + " | ".join(fmt(results[n]["summary"][key]) for n in names) + " |")
    lines += ["", "## Por pergunta", "", "| ID | Tipo | Pergunta | " + " | ".join(names) + " |",
              "|---|---|---|" + "---|" * len(names)]
    for qid, q in gold.items():
        cells = []
        for n in names:
            s = next(x for x in results[n]["scores"] if x["id"] == qid)
            c = "ok" if s["correct"] else ("erro" if s["error"] else "falha")
            if "recall" in s:
                c += f" (P {s['precision']:.2f} / R {s['recall']:.2f})"
            elif s["kind"] != "answerable":
                c += " (absteve)" if s["abstained"] else ""
            cells.append(c)
        lines.append(f"| {qid} | {q['kind']} | {q['question']} | " + " | ".join(cells) + " |")
    lines += ["", "## Falhas para analise", ""]
    for n in names:
        for s in results[n]["scores"]:
            if not s["correct"]:
                det = s.get("error") or ", ".join(f"{k}={s[k]}" for k in ("missing", "extra", "unsupported_ids", "abstained") if s.get(k))
                lines.append(f"- **{n} / {s['id']}**: {det or 'ver results_' + n + '.json'}")
    lines += ["", "Observacoes: as metricas de IDs comparam so o tipo de ID pedido pela pergunta. "
              "'ID sem suporte' = ID citado no texto da resposta que nao aparece no subgrafo, nas linhas nem nas fontes "
              "(proxy de alucinacao). Dados sinteticos: sinalizacao nao comprova fraude."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", nargs="+", default=["baseline", "vector"], help="baseline | vector | retrieval")
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--gold-only", action="store_true")
    ap.add_argument("--only", nargs="+", help="IDs de perguntas (ex.: A01 B02)")
    a = ap.parse_args()

    gold = build_gold(load_data(a.data))
    if a.only:
        gold = {k: v for k, v in gold.items() if k in a.only}
    if a.gold_only:
        for qid, q in gold.items():
            ids = q["gold_ids"]
            print(f"{qid} [{q['kind']}] {q['question']}\n     esperado ({len(ids)}): {', '.join(ids[:20])}{' ...' if len(ids) > 20 else ''}")
        return

    OUT.mkdir(exist_ok=True)
    results = {}
    for name, fn in make_backends(a.backends).items():
        print(f"\n== {name}")
        scores, raw = run_backend(fn, gold)
        results[name] = {"summary": summarize(scores), "scores": scores}
        (OUT / f"results_{name}.json").write_text(json.dumps({"summary": results[name]["summary"], "scores": scores,
                                                              "answers": raw}, ensure_ascii=False, indent=1, default=str),
                                                  encoding="utf-8")
    md = report(gold, results)
    (OUT / "report.md").write_text(md, encoding="utf-8")
    print("\n" + md.split("## Por pergunta")[0])
    print(f"Relatorio completo: {OUT / 'report.md'}")


if __name__ == "__main__":
    main()
