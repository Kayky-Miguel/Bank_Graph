"""Correcoes da Etapa 5 (graphrag_pipeline) sem Neo4j e sem LLM.

  python -m pytest tests -q
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("neo4j")

import graphrag_pipeline as G  # noqa: E402
from evaluate_qa import QUESTIONS  # noqa: E402


def test_all_templates_pass_validator():
    for name, t in G.TEMPLATES.items():
        ok, res = G.validate_cypher(t["cypher"], t.get("max_depth", G.MAX_DEPTH))
        assert ok, (name, res)


def test_schema_text_matches_data():
    # bugs anteriores: 'SOLE' nao existe (e PRIMARY) e Card nao tinha propriedades
    assert "SOLE" not in G.SCHEMA_TEXT and "'PRIMARY'|'JOINT'" in G.SCHEMA_TEXT
    assert "Card {card_id" in G.SCHEMA_TEXT


def test_guard_blocks_only_sensitive_and_ambiguous_eval_questions():
    blocked = {q["id"] for q in QUESTIONS if G.guard(q["question"])}
    assert blocked == {"U03", "M01", "M02"}


@pytest.mark.parametrize("q,blocked", [
    ("Qual é o CPF do cliente C0001?", True),
    ("Qual a senha da conta A0001?", True),
    ("Quais regras se aplicam ao perfil financeiro deste cliente?", True),
    ("Quais contas pertencem ao cliente C0208?", False),
    ("Quais clientes possuem contas conjuntas?", False),
])
def test_guard_cases(q, blocked):
    assert bool(G.guard(q)) is blocked


def test_resolve_plan_rejects_missing_or_invented_ids():
    q = "Quais cartoes o cliente C0352 possui?"
    with pytest.raises(ValueError, match="precisa informar o ID"):          # nao herda o ID de exemplo
        G.resolve_plan({"mode": "template", "template": "customer_cards", "params": {}}, q)
    with pytest.raises(ValueError, match="nao estao na pergunta"):
        G.resolve_plan({"mode": "template", "template": "customer_cards", "params": {"customer_id": "C0001"}}, q)
    with pytest.raises(ValueError, match="nao estao na pergunta"):
        G.resolve_plan({"mode": "cypher", "cypher": "MATCH (c:Customer {customer_id:'C0286'})-[:HAS_LOAN]->(l:Loan) "
                                                   "RETURN l.loan_id LIMIT 5"}, "E os emprestimos, estao ativos?")
    cy, params, origem = G.resolve_plan({"mode": "template", "template": "customer_cards",
                                         "params": {"customer_id": "c0352"}}, q)
    assert params["customer_id"] == "C0352" and origem == "template:customer_cards"


def test_clean_rows_detects_all_null():
    rows, all_null = G.clean_rows([{"k.card_number": None}, {"k.card_number": None}])
    assert all_null
    rows, all_null = G.clean_rows([{"a": "C0001", "b": None}, {"a": "C0002", "b": None}])
    assert not all_null and rows == [{"a": "C0001"}, {"a": "C0002"}]


def test_facts_list_is_complete_and_marks_empty_loans():
    rows = [{"cliente": "C0159", "conta": "A0001", "emprestimos_ativos": []},
            {"cliente": "C0208", "conta": "A0525", "emprestimos_ativos": ["L0041"]},
            {"cliente": "C0208", "conta": "A0525", "emprestimos_ativos": ["L0041"]}]       # duplicada
    txt = G.facts_list(rows)
    assert "(2 linhas)" in txt and "C0159" in txt and "emprestimos_ativos: nenhum" in txt and "L0041" in txt


class FakeDrv:
    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_retry_after_null_rows_and_list_appended(monkeypatch):
    plans = [{"mode": "cypher", "cypher": "MATCH (c:Customer {customer_id:'C0352'})-[:HAS_CARD]->(k:Card) "
                                          "RETURN k.card_number AS cartao LIMIT 5"},
             {"mode": "template", "template": "customer_cards", "params": {"customer_id": "C0352"}}]
    results = [[{"cartao": None}] * 3,
               [{"cliente": "C0352", "cartao": c, "conta": "A0052"} for c in ("CC0001", "CC0015", "CC0234")]]
    monkeypatch.setattr(G, "vector_search", lambda s, q, k=4: [])
    monkeypatch.setattr(G, "kag_rules", lambda s, ids: [])
    monkeypatch.setattr(G, "plan_query", lambda q, prov: plans.pop(0))
    monkeypatch.setattr(G, "run_graph_query", lambda s, c, p: results.pop(0))
    monkeypatch.setattr(G, "_llm", lambda *a, **k: "O cliente C0352 possui 3 cartoes.")
    r = G.answer("Quais cartões o cliente C0352 possui?", FakeDrv(), "mock")
    assert r["query_origin"] == "template:customer_cards" and not r["abstained"]
    assert "tentativa 1" in r["errors"][0] and "nulos" in r["errors"][0]
    assert all(c in r["answer"] for c in ("CC0001", "CC0015", "CC0234"))
    assert r["unsupported_ids"] == []


def test_guard_answers_without_llm(monkeypatch):
    monkeypatch.setattr(G, "_llm", lambda *a, **k: pytest.fail("LLM nao deveria ser chamado"))
    r = G.answer("E os empréstimos dele, estão ativos?", FakeDrv(), "mock")
    assert r["abstained"] and "ID do cliente" in r["answer"] and r["cypher"] is None


@pytest.mark.parametrize("qid,template", [
    ("B04", "customer_cards"), ("B05", "transaction_evidence"), ("I01", "joint_accounts"),
    ("I02", "joint_accounts_active_loan"), ("I05", "merchant_customers"), ("A02", "indirect_joint"),
    ("A01", "flagged_with_loan"), ("I03", "merchant_concentration"), ("A07", "path_between_customers"),
    ("A08", "central_merchants")])
def test_mock_planner_routes_to_new_templates(qid, template):
    q = next(x["question"] for x in QUESTIONS if x["id"] == qid)
    plan = json.loads(G._mock_llm("", f"Pergunta: {q}\nresto", want_json=True))
    assert plan["template"] == template
    G.resolve_plan(plan, q)            # e o plano passa no validador e na checagem de IDs


def _fake_answer(monkeypatch, plans, rows):
    calls = {"plans": 0}

    def plan(q, prov):
        calls["plans"] += 1
        calls["last_q"] = q
        return plans.pop(0)

    monkeypatch.setattr(G, "vector_search", lambda s, q, k=4: [])
    monkeypatch.setattr(G, "kag_rules", lambda s, ids: [])
    monkeypatch.setattr(G, "plan_query", plan)
    monkeypatch.setattr(G, "run_graph_query", lambda s, c, p: rows)
    monkeypatch.setattr(G, "_llm", lambda *a, **k: "O cliente C0208 tem 2 contas.")
    return calls


def test_replans_when_llm_skips_data_query_for_question_with_id(monkeypatch):
    # rodada final: o planejador devolveu 'none' para "contas do C0208"; a pergunta cita um ID de dados
    calls = _fake_answer(monkeypatch,
                         [{"mode": "none"},
                          {"mode": "template", "template": "customer_accounts", "params": {"customer_id": "C0208"}}],
                         [{"cliente": "C0208", "conta": "A0525"}, {"cliente": "C0208", "conta": "A0689"}])
    r = G.answer("Quais contas pertencem ao cliente C0208?", FakeDrv(), "mock")
    assert calls["plans"] == 2 and "C0208" in calls["last_q"]
    assert r["query_origin"] == "template:customer_accounts" and not r["abstained"]
    assert "A0525" in r["answer"] and "A0689" in r["answer"]
    assert len(r["plans"]) == 2


def test_no_replan_for_rule_question_without_data_id(monkeypatch):
    calls = _fake_answer(monkeypatch, [{"mode": "none"}], [])
    G.answer("Qual é o limite do PIX para o segmento BASIC?", FakeDrv(), "mock")
    assert calls["plans"] == 1


def test_wrong_id_gets_second_chance_when_question_has_id(monkeypatch):
    calls = _fake_answer(monkeypatch,
                         [{"mode": "template", "template": "customer_accounts", "params": {"customer_id": "C0001"}},
                          {"mode": "template", "template": "customer_accounts", "params": {"customer_id": "C0208"}}],
                         [{"cliente": "C0208", "conta": "A0525"}])
    r = G.answer("Quais contas pertencem ao cliente C0208?", FakeDrv(), "mock")
    assert calls["plans"] == 2 and r["params"]["customer_id"] == "C0208"


def test_guard_message_has_no_example_id():
    msg = G.guard("Quais contas pertencem ao cliente?")
    assert msg and not G._ANY_ID.search(msg.upper())
