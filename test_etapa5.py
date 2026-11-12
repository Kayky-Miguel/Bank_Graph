"""Testes que NAO precisam de Neo4j nem de chave. Rode: python test_etapa5.py"""
from graphrag_pipeline import validate_cypher, resolve_plan, TEMPLATES

# 1) todas as consultas prontas passam no proprio validador
for n, t in TEMPLATES.items():
    ok, r = validate_cypher(t["cypher"], t.get("max_depth", 4)); assert ok, (n, r)

# 2) consultas perigosas ou fora do schema precisam ser rejeitadas
bad = {
 "escrita":      "MATCH (c:Customer) SET c.name='x' RETURN c",
 "delete":       "MATCH (c:Customer) DETACH DELETE c RETURN 1",
 "create":       "CREATE (c:Customer {customer_id:'X'}) RETURN c",
 "call":         "CALL db.labels() YIELD label RETURN label",
 "label":        "MATCH (p:Password) RETURN p LIMIT 5",
 "relacao":      "MATCH (c:Customer)-[:KNOWS]->(d:Customer) RETURN c LIMIT 5",
 "profundidade": "MATCH p=(c:Customer)-[:OWNS*1..9]-(x) RETURN p LIMIT 5",
 "sem limite*":  "MATCH p=(c:Customer)-[:OWNS*]-(x) RETURN p LIMIT 5",
 "limit alto":   "MATCH (c:Customer) RETURN c LIMIT 100000",
 "duas":         "MATCH (c:Customer) RETURN c; MATCH (a:Account) RETURN a",
 "sem return":   "MATCH (c:Customer)",
}
for n, q in bad.items():
    ok, r = validate_cypher(q); assert not ok, f"deveria rejeitar ({n}): {q}"
    print(f"rejeitada [{n}]: {r}")

# 3) consulta valida sem LIMIT recebe LIMIT automatico; string com palavra proibida nao confunde
ok, q = validate_cypher("MATCH (c:Customer {name:'SET CREATE'}) RETURN c.customer_id")
assert ok and q.endswith("LIMIT 50"), q

# 4) parametros do LLM sao forcados ao tipo certo e a data de referencia e fixa
_, p, _ = resolve_plan({"mode": "template", "template": "flagged_with_loan", "params": {"dias": "30"}})
assert p["dias"] == 30 and str(p["ref"]) == "2026-11-10"
_, p, _ = resolve_plan({"mode": "template", "template": "customer_accounts", "params": {"customer_id": " c0208 "}})
assert p["customer_id"] == "C0208"
try: resolve_plan({"mode": "none"}); raise SystemExit("deveria falhar")
except ValueError: pass
print("\nTODOS OS TESTES PASSARAM")

# ---- testes da Etapa 5 (v2): abstencao, IDs sem suporte e fluxo completo com banco/LLM simulados ----
import graphrag_pipeline as G
assert G.is_abstention("Não há evidência suficiente no grafo/documentos para responder.")   # com acento (bug real do teste anterior)
assert not G.is_abstention("O cliente C0208 possui duas contas.")
assert G.unsupported_ids("Cliente C0208 e C9999", ["C0208"]) == ["C9999"]

class FakeDrv:
    def session(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): pass
G.vector_search = lambda s, q, k=4: []                       # nenhum trecho relevante (como em 'capital da Franca')
G.kag_rules = lambda s, ids: []
G.run_graph_query = lambda s, c, p: []
# fora do dominio: planner diz 'none', nada recuperado -> deve se abster SEM chamar o LLM de resposta
G._llm = lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM nao deveria ser chamado"))
G.plan_query = lambda q, prov: {"mode": "none"}
r = G.answer("Qual a capital da França?", FakeDrv(), "mock")
assert r["abstained"] and r["errors"] == [] and r["confidence"] == "baixa", r
# resposta com ID inventado e marcada
G.run_graph_query = lambda s, c, p: [{"cliente": "C0208", "emprestimos_ativos": ["L0041"]}]
G.plan_query = lambda q, prov: {"mode": "template", "template": "flagged_with_loan", "params": {"dias": 30}}
G._llm = lambda *a, **k: "Clientes C0208 e C0999 tem emprestimo."
r = G.answer("x", FakeDrv(), "mock")
assert r["unsupported_ids"] == ["C0999"] and r["confidence"] == "baixa", r
print("TESTES v2 PASSARAM")

# ---- v3: ID escrito na pergunta nao e alucinacao; resposta so com regras tem confianca media ----
G.run_graph_query = lambda s, c, p: [{"emprestimo": "L0041", "regra": "R003", "documento": "DOC003"}]
G.plan_query = lambda q, prov: {"mode": "template", "template": "customer_loans_rules", "params": {"customer_id": "C0208"}}
G._llm = lambda *a, **k: "Cliente C0208, emprestimo L0041, regra R003 (DOC003)."
r = G.answer("Quais regras se aplicam aos empréstimos do cliente C0208?", FakeDrv(), "mock")
assert r["unsupported_ids"] == [] and r["confidence"] == "media" and not r["abstained"], r
G.run_graph_query = lambda s, c, p: []
G.plan_query = lambda q, prov: {"mode": "none"}
G.kag_rules = lambda s, ids: [{"documento": "DOC002", "regra": "R002"}]
G.vector_search = lambda s, q, k=4: [{"id": "DOC002", "label": "Document", "title": "t", "section": "2.3", "page": 9, "score": 0.8}]
G._llm = lambda *a, **k: "Não, alerta não comprova fraude (R002, DOC002)."
r = G.answer("Um alerta comprova fraude?", FakeDrv(), "mock")
assert not r["abstained"] and r["confidence"] == "media" and r["errors"] == [], r
print("TESTES v3 PASSARAM")
