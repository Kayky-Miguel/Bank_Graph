"""BankGraph AI - Etapa 5: recuperacao hibrida GraphRAG/KAG.

Fluxo (cada numero e uma funcao abaixo):
  1. vector_search   - embedding da pergunta -> trechos/regras parecidos (indice vetorial)
  2. plan_query      - LLM escolhe uma consulta pronta (template) OU propoe um Cypher
  3. validate_cypher - guarda-corpo: so leitura, so labels/relacoes permitidos, profundidade e LIMIT
  4. run_graph_query - executa no Neo4j com parametros, em modo leitura e com timeout
  5. kag_rules       - busca regras explicitas (BankingRule/RuleTopic) ligadas aos documentos achados
  6. generate_answer - LLM responde SO com o contexto recuperado; sem evidencia -> abstem-se
  7. answer()        - junta tudo e devolve um dicionario com resposta + evidencias

Uso:
  export NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=...  (e OPENAI_API_KEY para o LLM real)
  python graphrag_pipeline.py "Quais clientes com alerta recente tem emprestimo ativo?"
  python graphrag_pipeline.py "..." --provider mock        # sem chave de API (so para testar o fluxo)
"""
import argparse, datetime as dt, json, os, re, time

# ---------------------------------------------------------------- configuracao
REF_DATE = dt.date.fromisoformat(os.environ.get("REF_DATE", "2026-11-10"))  # dados terminam aqui
EMBED_MODEL = os.environ.get("EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")  # 384 dim, igual embed_docs.py
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
MAX_DEPTH, MAX_LIMIT, DEFAULT_LIMIT, QUERY_TIMEOUT_S = 4, 100, 50, 15
MIN_VECTOR_SCORE = 0.60   # abaixo disso o trecho e irrelevante (calibrado: pergunta fora do dominio ~0.56; relevantes >= 0.64)

# O que o LLM pode usar. Tudo fora destas listas e rejeitado pelo validador.
ALLOWED_LABELS = {"Customer", "Account", "Transaction", "Merchant", "Alert", "Loan", "Card", "Branch",
                  "Employee", "Complaint", "Document", "BankingRule", "RuleTopic", "Segment", "Limit",
                  "Term", "Condition", "Action", "Obligation", "Entity"}
ALLOWED_RELS = {"OWNS", "SENT", "PAID_TO", "RAISED_ON", "HAS_LOAN", "ON_ACCOUNT", "HAS_CARD", "LINKED_TO",
                "BELONGS_TO", "WORKS_AT", "FILED", "ABOUT", "DESCRIBES", "FOLLOWS", "MENTIONS", "INSTANCE_OF",
                "APPLIES_TO", "HAS_LIMIT", "HAS_TERM", "REQUIRES", "MAY_TRIGGER", "MUST_RECORD"}

# Conferido contra os CSVs e o ingest.py: nomes de propriedade e valores EXATOS (o LLM nao deve adivinhar).
SCHEMA_TEXT = """Grafo Neo4j (dados sinteticos). Use SOMENTE estes labels, relacoes e propriedades (nomes exatos).
(Customer {customer_id,name,birth_year,city,state,segment:'BASIC'|'STANDARD'|'PREMIUM',monthly_income_brl,registration_date,pagerank,community})
  -[:OWNS {ownership_type:'PRIMARY'|'JOINT'}]->
(Account {account_id,account_type:'CHECKING'|'SAVINGS'|'PAYMENT',status:'ACTIVE'|'BLOCKED'|'CLOSED',opened_date,simulated_balance_brl})
(Account)-[:SENT]->(Transaction {transaction_id,amount_brl,transaction_type:'PIX_TRANSFER'|'TED_TRANSFER'|'CARD_PURCHASE'|'BILL_PAYMENT'|'WITHDRAWAL',
  date,timestamp,status:'COMPLETED'|'PENDING'|'REVERSED',channel:'APP'|'WEB'|'ATM'|'POS',flagged:true|false,scenario})
(Transaction)-[:PAID_TO]->(Merchant {merchant_id,merchant_name,category,city,state,risk_profile:'LOW'|'MEDIUM'|'HIGH',active,pagerank,community})
(Alert {alert_id,alert_type:'UNUSUAL_AMOUNT'|'UNUSUAL_HOUR'|'RISKY_MERCHANT'|'HIGH_FREQUENCY',severity:'LOW'|'MEDIUM'|'HIGH',alert_date,status,note})-[:RAISED_ON]->(Transaction)
(Customer)-[:HAS_LOAN]->(Loan {loan_id,principal_brl,annual_interest_rate_pct,installments_total,installments_paid,status:'ACTIVE'|'LATE'|'PAID'|'CANCELLED',start_date})-[:ON_ACCOUNT]->(Account)
(Customer)-[:HAS_CARD]->(Card {card_id,brand:'VISA'|'MASTERCARD'|'ELO',card_type:'CREDIT'|'DEBIT',credit_limit_brl,status:'ACTIVE'|'BLOCKED'})-[:LINKED_TO]->(Account)
(Account)-[:BELONGS_TO]->(Branch {branch_id,branch_name,city,state})<-[:WORKS_AT]-(Employee {employee_id,employee_name,role})
(Customer)-[:FILED]->(Complaint {complaint_id,category,description,status,created_date})-[:ABOUT]->(Transaction)
(Document {document_id,title,section,page,version,text})-[:DESCRIBES]->(BankingRule {rule_id,rule_name,description,applies_to,severity,is_active})
(Loan)-[:FOLLOWS]->(BankingRule)
(BankingRule)-[:INSTANCE_OF]->(RuleTopic {name})-[:APPLIES_TO|HAS_LIMIT|HAS_TERM|REQUIRES|MAY_TRIGGER|MUST_RECORD]->(Entity {name,type})
pagerank e community vem de graph_algorithms.py (PageRank e comunidades Louvain da rede cliente-estabelecimento).
IDs: Customer C0001, Account A0001, Transaction T0000001, Loan L0001, Card CC0001, Merchant M0001, Alert AL00001, Document DOC001, BankingRule R001.
Datas (date, opened_date, alert_date, start_date...) sao tipo date do Cypher. Parametros disponiveis: $ref (data de referencia).
Nunca use datetime()/date() sem argumento. Prefira retornar propriedades (c.customer_id AS cliente) em vez de nos inteiros."""

# ---------------------------------------------------------------- consultas prontas (plano B e base do KAG)
TEMPLATES = {
    "flagged_with_loan": {
        "descricao": "Clientes com transacao sinalizada nos ultimos N dias e (opcionalmente) emprestimo ativo. PERGUNTA CENTRAL.",
        "params": {"dias": 30},
        "cypher": """MATCH (c:Customer)-[:OWNS]->(a:Account)-[:SENT]->(t:Transaction {flagged:true})
WHERE t.date >= $ref - duration({days: $dias})
OPTIONAL MATCH (t)<-[:RAISED_ON]-(al:Alert)
OPTIONAL MATCH (c)-[:HAS_LOAN]->(l:Loan {status:'ACTIVE'})
RETURN c.customer_id AS cliente, a.account_id AS conta, t.transaction_id AS transacao, t.amount_brl AS valor,
       collect(DISTINCT al.alert_type) AS alertas, collect(DISTINCT l.loan_id) AS emprestimos_ativos
ORDER BY cliente LIMIT 50"""},
    "indirect_joint": {
        "descricao": "Relacao INDIRETA (multi-hop): cliente que divide conta conjunta com quem tem transacao sinalizada.",
        "params": {"dias": 365},
        "cypher": """MATCH (x:Customer)-[:OWNS]->(:Account)<-[:OWNS]-(y:Customer)-[:OWNS]->(:Account)-[:SENT]->(t:Transaction {flagged:true})
WHERE x <> y AND t.date >= $ref - duration({days: $dias})
OPTIONAL MATCH (x)-[:HAS_LOAN]->(l:Loan {status:'ACTIVE'})
RETURN x.customer_id AS cliente_indireto, y.customer_id AS via_cliente, t.transaction_id AS transacao,
       collect(DISTINCT l.loan_id) AS emprestimos_ativos
LIMIT 50"""},
    "customer_accounts": {
        "descricao": "Contas (e tipo de titularidade) de um cliente.",
        "params": {"customer_id": "C0001"},
        "cypher": """MATCH (c:Customer {customer_id:$customer_id})-[o:OWNS]->(a:Account)
RETURN c.customer_id AS cliente, a.account_id AS conta, a.account_type AS tipo, a.status AS status,
       o.ownership_type AS titularidade, a.simulated_balance_brl AS saldo_simulado LIMIT 50"""},
    "customer_loans_rules": {
        "descricao": "Emprestimos de um cliente + regras que se aplicam + documento de origem (KAG).",
        "params": {"customer_id": "C0001"},
        "cypher": """MATCH (c:Customer {customer_id:$customer_id})-[:HAS_LOAN]->(l:Loan)
OPTIONAL MATCH (l)-[:FOLLOWS]->(r:BankingRule)<-[:DESCRIBES]-(d:Document)
RETURN c.customer_id AS cliente, l.loan_id AS emprestimo, l.status AS status, l.principal_brl AS valor, r.rule_id AS regra,
       r.rule_name AS nome_regra, r.description AS descricao_regra, d.document_id AS documento,
       d.title AS titulo, d.section AS secao, d.page AS pagina LIMIT 50"""},
    "merchant_concentration": {
        "descricao": "Estabelecimentos que concentram pagamentos de varios clientes distintos.",
        "params": {},
        "cypher": """MATCH (c:Customer)-[:OWNS]->(:Account)-[:SENT]->(:Transaction)-[:PAID_TO]->(m:Merchant)
RETURN m.merchant_id AS estabelecimento, m.merchant_name AS nome, count(DISTINCT c) AS clientes
ORDER BY clientes DESC LIMIT 10"""},
    "flagged_evidence": {
        "descricao": "Evidencias de por que transacoes foram sinalizadas (alerta, estabelecimento, conta, cliente).",
        "params": {},
        "cypher": """MATCH (al:Alert)-[:RAISED_ON]->(t:Transaction {flagged:true})<-[:SENT]-(a:Account)<-[:OWNS]-(c:Customer)
MATCH (t)-[:PAID_TO]->(m:Merchant)
RETURN t.transaction_id AS transacao, al.alert_id AS alerta, al.alert_type AS tipo_alerta, al.severity AS severidade,
       al.alert_date AS data_alerta, t.amount_brl AS valor, m.merchant_id AS estabelecimento,
       a.account_id AS conta, c.customer_id AS cliente
ORDER BY data_alerta DESC LIMIT 10"""},
    "transaction_evidence": {
        "descricao": "Evidencias de UMA transacao especifica (pelo ID T...): valores, cenario, alertas, estabelecimento, conta e cliente.",
        "params": {"transaction_id": "T0000001"},
        "cypher": """MATCH (t:Transaction {transaction_id:$transaction_id})
OPTIONAL MATCH (a:Account)-[:SENT]->(t)
OPTIONAL MATCH (c:Customer)-[:OWNS]->(a)
OPTIONAL MATCH (t)-[:PAID_TO]->(m:Merchant)
OPTIONAL MATCH (al:Alert)-[:RAISED_ON]->(t)
RETURN t.transaction_id AS transacao, t.amount_brl AS valor, t.transaction_type AS tipo, t.date AS data,
       t.flagged AS sinalizada, t.scenario AS cenario_simulado, al.alert_id AS alerta, al.alert_type AS tipo_alerta,
       al.severity AS severidade, al.note AS nota, m.merchant_id AS estabelecimento, m.risk_profile AS risco_estabelecimento,
       a.account_id AS conta, collect(DISTINCT c.customer_id) AS clientes LIMIT 10"""},
    "customer_cards": {
        "descricao": "Cartoes de um cliente (bandeira, tipo, limite, status, conta vinculada).",
        "params": {"customer_id": "C0001"},
        "cypher": """MATCH (c:Customer {customer_id:$customer_id})-[:HAS_CARD]->(k:Card)
OPTIONAL MATCH (k)-[:LINKED_TO]->(a:Account)
RETURN c.customer_id AS cliente, k.card_id AS cartao, k.brand AS bandeira, k.card_type AS tipo,
       k.credit_limit_brl AS limite, k.status AS status, a.account_id AS conta LIMIT 50"""},
    "joint_accounts": {
        "descricao": "LISTA de clientes que possuem conta conjunta (ownership_type JOINT), com os emprestimos ativos de cada um. "
                     "Para 'conta conjunta E emprestimo ativo', use este e filtre os que tem emprestimos_ativos nao vazio.",
        "params": {},
        "cypher": """MATCH (c:Customer)-[:OWNS {ownership_type:'JOINT'}]->(a:Account)
OPTIONAL MATCH (c)-[:HAS_LOAN]->(l:Loan {status:'ACTIVE'})
RETURN c.customer_id AS cliente, a.account_id AS conta_conjunta, collect(DISTINCT l.loan_id) AS emprestimos_ativos
ORDER BY cliente LIMIT 100"""},
    "joint_accounts_active_loan": {
        "descricao": "Clientes que tem conta conjunta E emprestimo ativo ao mesmo tempo.",
        "params": {},
        "cypher": """MATCH (c:Customer)-[:OWNS {ownership_type:'JOINT'}]->(a:Account)
MATCH (c)-[:HAS_LOAN]->(l:Loan {status:'ACTIVE'})
RETURN c.customer_id AS cliente, collect(DISTINCT a.account_id) AS contas_conjuntas, collect(DISTINCT l.loan_id) AS emprestimos_ativos
ORDER BY cliente LIMIT 100"""},
    "merchant_customers": {
        "descricao": "Clientes que pagaram a UM estabelecimento especifico (pelo ID M...), com quantidade e total pago.",
        "params": {"merchant_id": "M0001"},
        "cypher": """MATCH (c:Customer)-[:OWNS]->(:Account)-[:SENT]->(t:Transaction)-[:PAID_TO]->(m:Merchant {merchant_id:$merchant_id})
RETURN c.customer_id AS cliente, m.merchant_id AS estabelecimento, count(t) AS transacoes, round(sum(t.amount_brl), 2) AS total_brl
ORDER BY cliente LIMIT 100"""},
    # ---- algoritmos de grafo (graph_algorithms.py grava pagerank/community; shortestPath e nativo do Cypher)
    "path_between_customers": {
        "descricao": "Caminho MINIMO (shortestPath) que liga dois clientes (dois IDs C...): contas, transacoes e estabelecimentos no meio.",
        "params": {"customer_id": "C0001", "other_customer_id": "C0002"},
        "max_depth": 6,
        "cypher": """MATCH (a:Customer {customer_id:$customer_id}), (b:Customer {customer_id:$other_customer_id})
MATCH p = shortestPath((a)-[:OWNS|SENT|PAID_TO*..6]-(b))
RETURN [n IN nodes(p) | coalesce(n.customer_id, n.account_id, n.transaction_id, n.merchant_id)] AS caminho,
       length(p) AS saltos LIMIT 1"""},
    "central_merchants": {
        "descricao": "Estabelecimentos mais CENTRAIS da rede de pagamentos (PageRank), com a comunidade de cada um.",
        "params": {},
        "cypher": """MATCH (m:Merchant) WHERE m.pagerank IS NOT NULL
RETURN m.merchant_id AS estabelecimento, m.merchant_name AS nome, round(m.pagerank, 5) AS pagerank, m.community AS comunidade
ORDER BY pagerank DESC LIMIT 10"""},
    "communities_flagged": {
        "descricao": "COMUNIDADES (grupos detectados por Louvain) ordenadas por transacoes sinalizadas; indica grupos que merecem analise.",
        "params": {},
        "cypher": """MATCH (c:Customer) WHERE c.community IS NOT NULL
OPTIONAL MATCH (c)-[:OWNS]->(:Account)-[:SENT]->(t:Transaction {flagged:true})
WITH c.community AS comunidade, count(DISTINCT c) AS clientes, count(t) AS sinalizadas,
     collect(DISTINCT CASE WHEN t IS NOT NULL THEN c.customer_id END) AS clientes_com_sinal
RETURN comunidade, clientes, sinalizadas, round(1.0 * sinalizadas / clientes, 3) AS sinalizadas_por_cliente,
       clientes_com_sinal[..10] AS exemplos
ORDER BY sinalizadas DESC LIMIT 10"""},
    "customer_community": {
        "descricao": "Comunidade (Louvain) de UM cliente e os clientes mais centrais (PageRank) da mesma comunidade.",
        "params": {"customer_id": "C0001"},
        "cypher": """MATCH (c:Customer {customer_id:$customer_id})
MATCH (o:Customer) WHERE o.community = c.community AND o <> c
RETURN c.customer_id AS cliente, c.community AS comunidade, round(c.pagerank, 5) AS pagerank_cliente,
       o.customer_id AS outro_cliente, round(o.pagerank, 5) AS pagerank_outro
ORDER BY pagerank_outro DESC LIMIT 15"""},
}

# ---------------------------------------------------------------- 3. guarda-corpo
_FORBIDDEN = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|FOREACH|CALL|APOC|DBMS|GRANT|DENY|REVOKE|ALTER|USE|START|STOP|SHOW)\b", re.I)
_LABEL = re.compile(r"\(\s*\w*\s*((?::\s*[A-Za-z_]+\s*)+)")
_REL = re.compile(r"\[\s*\w*\s*:\s*([A-Za-z_|:\s]+)")

def _strip_strings(q):
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", q)

def validate_cypher(cypher, max_depth=MAX_DEPTH):
    """Retorna (ok, cypher_final_ou_motivo). So aceita UMA consulta de leitura dentro das listas permitidas."""
    q = cypher.strip().rstrip(";").strip()
    s = _strip_strings(q)
    if not s:
        return False, "consulta vazia"
    if ";" in s:
        return False, "mais de uma instrucao"
    if "//" in s or "/*" in s:
        return False, "comentarios nao permitidos"
    if not re.match(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND)\b", s, re.I):
        return False, "deve comecar com MATCH"
    bad = _FORBIDDEN.search(s)
    if bad:
        return False, f"palavra proibida: {bad.group(1).upper()}"
    if not re.search(r"\bRETURN\b", s, re.I):
        return False, "falta RETURN"
    for m in _LABEL.finditer(s):
        for lab in re.findall(r"[A-Za-z_]+", m.group(1)):
            if lab not in ALLOWED_LABELS:
                return False, f"label nao permitido: {lab}"
    for m in _REL.finditer(s):
        for rel in re.findall(r"[A-Za-z_]+", m.group(1)):
            if rel not in ALLOWED_RELS:
                return False, f"relacao nao permitida: {rel}"
    for m in re.finditer(r"\[[^\]]*?\*\s*(\d*)\s*(\.\.)?\s*(\d*)", s):   # caminhos de tamanho variavel dentro de [...]
        hi = m.group(3) if m.group(2) else m.group(1)
        if not hi or int(hi) > max_depth:
            return False, f"profundidade maxima e {max_depth}"
    lim = re.findall(r"\bLIMIT\s+(\d+)\s*$", s, re.I)
    if lim:
        if int(lim[-1]) > MAX_LIMIT:
            return False, f"LIMIT maximo e {MAX_LIMIT}"
    elif re.search(r"\bLIMIT\b", s, re.I):
        return False, "use LIMIT numerico no final"
    else:
        q += f" LIMIT {DEFAULT_LIMIT}"
    return True, q

# ---------------------------------------------------------------- LLM (provedor compativel com a API da OpenAI)
def llm_json(system, user, provider):
    return json.loads(_llm(system, user, provider, want_json=True))

def _llm(system, user, provider, want_json=False):
    if provider == "mock":
        return _mock_llm(system, user, want_json)
    from openai import OpenAI          # OPENAI_API_KEY e (opcional) OPENAI_BASE_URL vem do ambiente
    client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None)
    kw = {"response_format": {"type": "json_object"}} if want_json else {}
    r = client.chat.completions.create(model=LLM_MODEL, temperature=0, **kw,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return r.choices[0].message.content

def _mock_llm(system, user, want_json):
    """Simula o LLM por palavras-chave. So serve para testar o fluxo sem chave."""
    if want_json:
        import unicodedata
        pergunta = user.split("Pergunta:", 1)[-1].split("\n", 1)[0]      # so a pergunta, sem o catalogo
        q = unicodedata.normalize("NFKD", pergunta.lower()).encode("ascii", "ignore").decode()
        m = re.search(r"\bC\d{4}\b", pergunta.upper())
        tx = re.search(r"\bT\d{7}\b", pergunta.upper())
        mer = re.search(r"\bM\d{4}\b", pergunta.upper())
        ids_c = re.findall(r"\bC\d{4}\b", pergunta.upper())
        if len(ids_c) >= 2 and ("conect" in q or "caminho" in q or "lig" in q):
            t, p = "path_between_customers", {"customer_id": ids_c[0], "other_customer_id": ids_c[1]}
        elif "comunidade" in q and m: t, p = "customer_community", {"customer_id": m.group()}
        elif "comunidade" in q: t, p = "communities_flagged", {}
        elif "central" in q or "pagerank" in q: t, p = "central_merchants", {}
        elif "indiret" in q: t, p = "indirect_joint", {"dias": 365}
        elif "conjunta" in q and "emprest" in q: t, p = "joint_accounts_active_loan", {}
        elif "conjunta" in q: t, p = "joint_accounts", {}
        elif tx: t, p = "transaction_evidence", {"transaction_id": tx.group()}
        elif mer: t, p = "merchant_customers", {"merchant_id": mer.group()}
        elif m and "cart" in q: t, p = "customer_cards", {"customer_id": m.group()}
        elif m and ("emprest" in q or "regra" in q): t, p = "customer_loans_rules", {"customer_id": m.group()}
        elif m and "conta" in q: t, p = "customer_accounts", {"customer_id": m.group()}
        elif "estabelec" in q and "concentr" in q and "o que" not in q: t, p = "merchant_concentration", {}
        elif "evid" in q or "por que" in q: t, p = "flagged_evidence", {}
        elif "sinaliz" in q or "alerta" in q: t, p = "flagged_with_loan", {"dias": 30}
        else: return json.dumps({"mode": "none"})
        return json.dumps({"mode": "template", "template": t, "params": p})
    return "[MOCK] Resposta simulada. Com um LLM real, aqui entra o texto redigido a partir do contexto."

# ---------------------------------------------------------------- 1. busca vetorial
_embedder = None
def vector_search(session, question, k=4):
    global _embedder
    from sentence_transformers import SentenceTransformer
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    vec = _embedder.encode(question, normalize_embeddings=True).tolist()
    hits = []
    # ATENCAO: db.index.vector.queryNodes esta marcada como obsoleta nas versoes novas; confira a sintaxe SEARCH na doc.
    for index, idprop in (("document_embedding", "document_id"), ("rule_embedding", "rule_id")):
        rows = session.run(f"""CALL db.index.vector.queryNodes('{index}', $k, $vec) YIELD node, score
                              RETURN node.{idprop} AS id, labels(node)[0] AS label, score,
                                     coalesce(node.title, node.rule_name) AS title,
                                     coalesce(node.text, node.description) AS text,
                                     node.section AS section, node.page AS page""", k=k, vec=vec).data()
        hits += [r for r in rows if r["score"] >= MIN_VECTOR_SCORE]
    return sorted(hits, key=lambda r: -r["score"])[:k]

# ---------------------------------------------------------------- 2. planejamento
def plan_query(question, provider):
    cat = "\n".join(f'- {n}: {t["descricao"]} params={t["params"]}' for n, t in TEMPLATES.items())
    system = ("Voce converte perguntas sobre um grafo bancario SINTETICO em consultas de LEITURA. Responda SOMENTE JSON.\n"
              "- Prefira SEMPRE uma consulta pronta quando alguma servir; escreva Cypher so se nenhuma servir.\n"
              "- IDs (C0208, M0007, T0001050...) devem ser copiados EXATAMENTE da pergunta. Nunca invente IDs: "
              "se a pergunta se refere a um cliente/conta/transacao sem dar o ID, use mode 'none'.\n"
              "- Perguntas sobre o que uma REGRA diz ou o que acontece em uma situacao ('o que acontece quando...', "
              "'quais regras orientam...') sao respondidas pelos documentos: use mode 'none', a menos que citem um ID.\n"
              + SCHEMA_TEXT)
    user = f"""Pergunta: {question}

Opcoes de resposta (JSON):
1) consulta pronta: {{"mode":"template","template":"<nome>","params":{{...}}}}
2) Cypher proprio (apenas se nenhuma pronta servir; somente leitura, com RETURN e LIMIT, usando $ref/$parametros): {{"mode":"cypher","cypher":"...","params":{{...}}}}
3) nenhuma consulta de DADOS (clientes/contas/transacoes) e necessaria: pergunta conceitual ou sobre regras/politicas (ex.: "um alerta comprova fraude?"), fora do dominio, opiniao ou pedido de decisao: {{"mode":"none"}}

Consultas prontas:
{cat}"""
    return llm_json(system, user, provider)

_ANY_ID = re.compile(r"\b(?:DOC\d{3}|CC\d{4}|CP\d{5}|AL\d{5}|C\d{4}|A\d{4}|T\d{7}|L\d{4}|M\d{4}|B\d{3}|E\d{4}|R\d{3})\b")


def resolve_plan(plan, question=None):
    """Transforma o plano do LLM em (cypher, params, origem) ja validado. Levanta ValueError se nao der.
    Com `question`, todo ID usado na consulta precisa estar escrito na pergunta (o LLM nao pode inventar
    nem herdar o ID de exemplo do template)."""
    mode = plan.get("mode")
    params = dict(plan.get("params") or {})
    if mode == "template":
        t = TEMPLATES.get(plan.get("template"))
        if not t:
            raise ValueError("template desconhecido")
        cypher, origem = t["cypher"], f"template:{plan['template']}"
        max_depth = t.get("max_depth", MAX_DEPTH)          # so templates revisados podem passar de MAX_DEPTH
        defaults = dict(t["params"])
        for k, v in defaults.items():
            if isinstance(v, str) and k not in params:     # ID de exemplo NUNCA vira parametro real
                raise ValueError(f"parametro '{k}' ausente: a pergunta precisa informar o ID")
        params = {k: params.get(k, v) for k, v in defaults.items()}
        for k, v in defaults.items():                      # forca o tipo certo (LLM as vezes devolve texto)
            if isinstance(v, int): params[k] = max(1, min(int(params[k]), 3650))
            else: params[k] = str(params[k]).strip().upper()
    elif mode == "cypher":
        cypher, origem = plan.get("cypher", ""), "cypher_llm"
        max_depth = MAX_DEPTH
        params = {k: v for k, v in params.items() if isinstance(v, (str, int, float))}
    else:
        raise ValueError("sem consulta")
    ok, res = validate_cypher(cypher, max_depth)
    if not ok:
        raise ValueError(f"Cypher rejeitado: {res}")
    if question is not None:
        asked = set(_ANY_ID.findall(question.upper()))
        used = set(_ANY_ID.findall(_strip_strings(res).upper() + " " + res.upper())) | \
               {str(v).upper() for v in params.values() if isinstance(v, str) and _ANY_ID.fullmatch(str(v).upper())}
        invented = sorted(used - asked)
        if invented:
            raise ValueError(f"a consulta usa IDs que nao estao na pergunta: {invented}")
    params["ref"] = REF_DATE
    return res, params, origem

# ---------------------------------------------------------------- 4. execucao
def run_graph_query(session, cypher, params):
    from neo4j import unit_of_work
    @unit_of_work(timeout=QUERY_TIMEOUT_S)            # transacao de LEITURA com limite de tempo
    def work(tx):
        return tx.run(cypher, params).data()
    return session.execute_read(work)

# ---------------------------------------------------------------- 5. KAG
def kag_rules(session, doc_ids):
    if not doc_ids:
        return []
    return session.run("""MATCH (d:Document) WHERE d.document_id IN $ids
        OPTIONAL MATCH (d)-[:DESCRIBES]->(r:BankingRule)
        OPTIONAL MATCH (r)-[:INSTANCE_OF]->(t:RuleTopic)
        OPTIONAL MATCH (t)-[x]->(e)
        RETURN d.document_id AS documento, d.title AS titulo, d.section AS secao, d.page AS pagina,
               r.rule_id AS regra, r.description AS descricao, t.name AS tema,
               collect(DISTINCT {relacao: type(x), entidade: e.name, tipo: head(labels(e))}) AS fatos
        LIMIT 20""", ids=doc_ids).data()

# ---------------------------------------------------------------- 6. resposta fundamentada
ANSWER_SYSTEM = """Voce responde perguntas sobre um sistema bancario SINTETICO usando EXCLUSIVAMENTE o CONTEXTO fornecido.
Regras: (1) nao use conhecimento externo; (2) abstenha-se, comecando EXATAMENTE por 'Não há evidência suficiente no grafo/documentos', SOMENTE se o contexto nao contiver informacao que responda a pergunta;
se o contexto tiver uma regra ou fato que responde (ex.: uma regra dizendo que 'alerta nao comprova fraude'), responda DIRETAMENTE com ele e cite o ID, sem usar a frase de abstencao;
se 'fatos_do_grafo' tiver linhas, elas SAO o resultado da consulta feita para esta pergunta: use-as, nao se abstenha;
(3) cite os IDs (clientes, contas, transacoes, regras, documentos) que sustentam cada afirmacao; (4) alertas e transacoes sinalizadas
sao sinais simulados e NAO comprovam fraude: nunca afirme fraude; (5) nao tome nem recomende decisoes financeiras; (6) responda em portugues, de forma curta.
(7) LISTAS: diga quantos itens atendem a pergunta e destaque os principais. A lista COMPLETA de IDs e anexada automaticamente pelo sistema logo abaixo da sua resposta, entao nao precisa repetir todos;
(8) use as colunas como estao: uma lista vazia em 'emprestimos_ativos' significa que o cliente NAO tem emprestimo ativo."""

_ID = _ANY_ID      # mesmo padrao em todo o pipeline (inclui cartoes CC e reclamacoes CP)

# Protecoes que NAO dependem do LLM (rodam antes dele)
_SENSITIVE = re.compile(r"\b(cpf|rg|senha|cvv|numero do cartao|pin)\b")
_REFERENCE = re.compile(r"\b(dele|dela|deles|delas|deste cliente|desse cliente|este cliente|esse cliente|"
                        r"(?:o|ao|do|pelo|para o) cliente)\b")


def _plain(t):
    import unicodedata
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower().strip()


def guard(question):
    """Resposta de abstencao pronta, ou None se a pergunta pode seguir para o pipeline."""
    q = _plain(question)
    if _SENSITIVE.search(q):
        return ("Não há evidência suficiente no grafo/documentos: o sistema não armazena dados pessoais sensíveis "
                "(CPF, RG, senhas, número de cartão). Os dados são sintéticos e só têm IDs fictícios.")
    if _REFERENCE.search(q) and not _ANY_ID.search(question.upper()):
        return ("Não há evidência suficiente no grafo/documentos: a pergunta se refere a um cliente sem informar qual. "
                "Informe o ID do cliente (ex.: C0208).")
    return None


def is_abstention(text):
    return _plain(text).startswith(("nao ha evidencia", "nao ha dados", "nao ha informac"))


def unsupported_ids(answer_text, evidence_ids):
    """IDs que o LLM citou na resposta mas que NAO estao nas evidencias recuperadas (sinal de alucinacao)."""
    return sorted(set(_ID.findall(answer_text)) - set(evidence_ids))


def clean_rows(rows):
    """Remove colunas sempre nulas. Se TODAS forem nulas, a consulta usou propriedade inexistente."""
    if not rows:
        return rows, False
    cols = [k for k in rows[0] if any(r.get(k) not in (None, [], "") for r in rows)]
    return [{k: r.get(k) for k in cols} for r in rows], not cols


def facts_list(rows, limit=100):
    """Lista completa e deterministica dos IDs de cada linha (o LLM pode omitir itens; o codigo nao)."""
    lines, seen = [], set()
    for r in rows[:limit]:
        parts = []
        for k, v in r.items():
            vals = v if isinstance(v, list) else [v]
            ids = [str(x) for x in vals if isinstance(x, str) and _ANY_ID.fullmatch(x)]
            if ids:
                parts.append(f"{k}: {', '.join(ids)}")
            elif isinstance(v, list) and not v and k.startswith(("emprestimo", "alerta")):
                parts.append(f"{k}: nenhum")
        line = " | ".join(parts)
        if line and line not in seen:
            seen.add(line)
            lines.append("- " + line)
    if not lines:
        return ""
    extra = f" (primeiras {limit} de {len(rows)})" if len(rows) > limit else ""
    return f"\n\nDados recuperados do grafo ({len(lines)} linhas{extra}):\n" + "\n".join(lines)


def generate_answer(question, graph_rows, rules, hits, provider):
    ctx = {"total_de_linhas_do_grafo": len(graph_rows), "fatos_do_grafo": graph_rows[:40],
           "regras_e_documentos": rules, "trechos_semanticos": hits}
    user = f"PERGUNTA: {question}\n\nCONTEXTO (JSON):\n{json.dumps(ctx, ensure_ascii=False, default=str)[:16000]}"
    return _llm(ANSWER_SYSTEM, user, provider)


def query_graph(s, question, provider, out, attempts=2):
    """Planeja, valida e executa. Se a consulta for rejeitada, falhar ou so devolver nulos, o LLM recebe o
    motivo e tenta mais uma vez. Retorna as linhas (possivelmente vazias)."""
    feedback = ""
    for attempt in range(attempts):
        plan = plan_query(question + feedback, provider)
        if plan.get("mode") == "none":
            out["query_origin"] = "none (so documentos/regras)"
            return []
        try:
            cypher, params, origem = resolve_plan(plan, question)
            out.update(cypher=cypher, params={k: str(v) for k, v in params.items()}, query_origin=origem)
            rows, all_null = clean_rows(run_graph_query(s, cypher, params))
            if all_null:
                raise ValueError("a consulta so devolveu valores nulos (propriedade inexistente?)")
            return rows
        except Exception as e:
            out["errors"].append(f"consulta ao grafo (tentativa {attempt + 1}): {e}")
            if "nao estao na pergunta" in str(e) or "precisa informar o ID" in str(e):
                return []                                   # faltou informacao na pergunta: nao insistir
            feedback = (f"\n\n(A tentativa anterior falhou: {e}. Use uma consulta pronta se alguma servir; "
                        "senao use SOMENTE as propriedades listadas no schema.)")
    return []


def answer(question, driver, provider="openai"):
    """Pipeline completo. Devolve um dicionario: e o 'contrato' com a interface (Etapa 6) e a avaliacao (Etapa 7)."""
    t0 = time.time()
    out = {"question": question, "answer": None, "abstained": False, "cypher": None, "params": None,
           "query_origin": None, "graph_rows": [], "documents": [], "rules": [], "entity_ids": [],
           "confidence": "baixa", "unsupported_ids": [], "errors": [], "latency_s": None}
    blocked = guard(question)
    if blocked:                                          # protecao deterministica: nem consulta nem LLM
        out.update(answer=blocked, abstained=True, query_origin="guarda (pergunta sem ID ou dado sensivel)",
                   latency_s=round(time.time() - t0, 2))
        return out
    hits = []
    with driver.session() as s:
        try:
            hits = vector_search(s, question)
        except Exception as e:                           # ex.: indice sem embeddings
            out["errors"].append(f"busca vetorial falhou: {e}")
        try:
            out["graph_rows"] = query_graph(s, question, provider, out)
        except Exception as e:
            out["errors"].append(f"consulta ao grafo: {e}")
        doc_ids = sorted({h["id"] for h in hits if h["label"] == "Document"} |
                         {r["documento"] for r in out["graph_rows"] if r.get("documento")})
        try:
            out["rules"] = kag_rules(s, doc_ids)
        except Exception as e:
            out["errors"].append(f"regras (KAG): {e}")
    out["documents"] = [{k: h[k] for k in ("id", "label", "title", "section", "page", "score")} for h in hits]
    if not out["graph_rows"] and not out["rules"] and not hits:        # nada recuperado -> abstencao, sem chamar o LLM
        out["abstained"] = True
        out["answer"] = "Não há evidência suficiente no grafo/documentos para responder a esta pergunta."
    else:
        out["answer"] = generate_answer(question, out["graph_rows"], out["rules"], hits, provider)
        out["abstained"] = is_abstention(out["answer"])
        if not out["abstained"]:
            out["answer"] += facts_list(out["graph_rows"])
        out["confidence"] = ("alta" if out["graph_rows"] and (out["rules"] or hits)
                             else "media" if (out["graph_rows"] or out["rules"]) else "baixa")   # heuristica, NAO e probabilidade
    out["entity_ids"] = sorted(set(_ID.findall(json.dumps([out["graph_rows"], out["rules"], hits], default=str))))
    out["unsupported_ids"] = unsupported_ids(out["answer"] or "", out["entity_ids"] + _ID.findall(question.upper()))
    if out["unsupported_ids"]:
        out["confidence"] = "baixa"
        out["errors"].append(f"IDs citados sem evidencia: {out['unsupported_ids']}")
    out["latency_s"] = round(time.time() - t0, 2)
    return out


def get_driver():
    from neo4j import GraphDatabase
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    try:   # esconde o aviso 'deprecated' da busca vetorial (a funcao continua funcionando)
        d = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth, notifications_disabled_classifications=["DEPRECATION"])
    except TypeError:
        d = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth)
    d.verify_connectivity()
    return d

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--provider", default="openai", choices=["openai", "mock"])
    a = ap.parse_args()
    drv = get_driver()
    res = answer(a.question, drv, a.provider)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    drv.close()
