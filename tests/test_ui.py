"""Testes da Etapa 6 sem Neo4j: subgrafo, contrato, roteamento e a propria interface (AppTest).

  python -m pytest tests -q
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_view import caption, collect_graph, render_html  # noqa: E402
from ui_backend import BaselineRetriever, call_backend, normalize_result  # noqa: E402


# ---------------- objetos falsos com a mesma "cara" dos tipos do driver neo4j
class FakeNode(dict):
    def __init__(self, eid, labels, **props):
        super().__init__(props)
        self.element_id, self.labels = eid, frozenset(labels)


class FakeRel(dict):
    def __init__(self, eid, rtype, start, end, **props):
        super().__init__(props)
        self.element_id, self.type, self.start_node, self.end_node = eid, rtype, start, end


class FakePath:
    def __init__(self, *rels):
        self.relationships = list(rels)
        self.nodes = [rels[0].start_node] + [r.end_node for r in rels]


C = FakeNode("n1", ["Customer"], customer_id="C0208", name="Ana", segment="BASIC")
A = FakeNode("n2", ["Account"], account_id="A0001", account_type="CHECKING", status="ACTIVE")
T = FakeNode("n3", ["Transaction"], transaction_id="T0001050", flagged=True, embedding=[0.1] * 384)
L = FakeNode("n4", ["Loan"], loan_id="L0001", status="ACTIVE", principal_brl=1000.0)
OWNS = FakeRel("r1", "OWNS", C, A, ownership_type="PRIMARY")
SENT = FakeRel("r2", "SENT", A, T)
HAS_LOAN = FakeRel("r3", "HAS_LOAN", C, L)


def test_collect_graph_dedup_and_hides_embedding():
    p = FakePath(OWNS, SENT)
    g = collect_graph([p, p, {"x": HAS_LOAN}], None, [[T]])
    assert sorted(n["id"] for n in g["nodes"]) == ["n1", "n2", "n3", "n4"]
    assert sorted(r["type"] for r in g["relationships"]) == ["HAS_LOAN", "OWNS", "SENT"]
    tx = next(n for n in g["nodes"] if n["id"] == "n3")
    assert "embedding" not in tx["props"]
    assert caption(tx) == "T0001050"


def test_render_html_contains_nodes():
    g = collect_graph(FakePath(OWNS, SENT))
    out = render_html(g, highlight=["C0208"])
    assert "C0208" in out and "OWNS" in out and "<html" in out.lower()


def test_normalize_result_defaults_and_records():
    res = normalize_result({"answer": "ok", "cypher": "MATCH (n) RETURN n", "records": [FakePath(OWNS)],
                            "sources": ["trecho"], "notes": "aviso"}, "pergunta")
    assert res["queries"][0]["cypher"] == "MATCH (n) RETURN n"
    assert len(res["graph"]["nodes"]) == 2
    assert res["sources"] == [{"text": "trecho"}] and res["notes"] == ["aviso"]
    empty = normalize_result({}, "q")
    assert empty["insufficient_evidence"] is True


def test_call_backend_passes_only_accepted_kwargs():
    seen = {}

    def only_question(q):
        seen["q"] = q
        return {"answer": "x"}

    def with_ref(q, ref_date=None):
        seen["ref"] = ref_date
        return {"answer": "y"}

    assert call_backend(only_question, "a", ref_date="2026-11-10", limit=5)["answer"] == "x"
    call_backend(with_ref, "b", ref_date="2026-11-10", limit=5)
    assert seen == {"q": "a", "ref": "2026-11-10"}


@pytest.mark.parametrize("question,intent", [
    ("Quais clientes possuem relacionamento com contas que realizaram transações sinalizadas nos últimos 30 dias?", "sinalizadas"),
    ("Quais contas pertencem ao cliente C0208?", "cliente"),
    ("Por quais evidências a transação T0001050 foi sinalizada?", "transacao"),
    ("Quais clientes possuem contas conjuntas?", "conjunta"),
    ("Quais clientes têm relação indireta com contas que apresentaram transações sinalizadas?", "indireta"),
    ("Quais estabelecimentos concentram pagamentos de vários clientes?", "estabelecimentos"),
    ("Quais regras orientam a revisão de transferências recorrentes?", "documentos"),
    ("Um alerta permite afirmar que houve fraude?", "documentos"),
])
def test_route(question, intent):
    assert BaselineRetriever(driver=object()).route(question)[0] == intent


def test_route_days_window():
    r = BaselineRetriever(driver=object())
    assert r.route("transações sinalizadas nos últimos 90 dias")[1]["dias"] == 90


class StubRetriever(BaselineRetriever):
    """Baseline com run() trocado por respostas prontas (sem Neo4j)."""

    def __init__(self, answers):
        super().__init__(driver=object(), embed=lambda t: [0.0] * 384)
        self.answers, self.calls = answers, []

    def run(self, cypher, params):
        self.calls.append((cypher, params))
        return self.answers.pop(0)


def test_flagged_handler_answer_and_graph():
    rec = {"cliente": "C0208", "transacoes": ["T0001050"], "emprestimos_ativos": ["L0001"],
           "caminhos": [FakePath(OWNS, SENT), FakePath(HAS_LOAN)]}
    r = StubRetriever([[rec]])
    res = normalize_result(r.answer("clientes com transações sinalizadas e empréstimo ativo"), "q")
    assert "C0208" in res["answer"] and "1 tem emprestimo ativo" in res["answer"]
    assert res["queries"][0]["params"] == {"ref": "2026-11-10", "dias": 30, "limit": 25}
    assert len(res["graph"]["nodes"]) == 4


def test_documents_abstains_on_low_similarity():
    rec = {"document_id": "DOC001", "title": "PIX", "section": "1", "page": 1, "version": 1, "text": "t",
           "score": 0.2, "regras": [], "caminhos": []}
    r = StubRetriever([[rec]])
    res = normalize_result(r.answer("previsao do tempo amanha"), "q")
    assert res["insufficient_evidence"] and res["confidence"] == "baixa"
    assert res["queries"][0]["params"]["vec"].startswith("<embedding")


def test_fraud_question_gets_disclaimer():
    rec = {"document_id": "DOC002", "title": "Transacoes Atipicas", "section": "1", "page": 1, "version": 1,
           "text": "t", "score": 0.7, "regras": [{"rule_id": "R004", "rule_name": "Transacoes Atipicas",
                                                    "description": "gera alerta"}], "caminhos": []}
    res = normalize_result(StubRetriever([[rec]]).answer("Um alerta permite afirmar que houve fraude?"), "q")
    assert res["notes"][0].startswith("Os dados nao permitem afirmar fraude")


# ---------------- a interface de ponta a ponta, com uma Etapa 5 falsa
def test_app_renders_with_fake_retriever(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    (tmp_path / "fake_retrieval.py").write_text(
        "def answer(question, ref_date=None, limit=25):\n"
        "    return {'answer': 'Resposta de teste para ' + question, 'confidence': 'alta',\n"
        "            'queries': [{'cypher': 'MATCH (c:Customer) RETURN c', 'params': {'x': 1}, 'rows': 1}],\n"
        "            'graph': {'nodes': [{'id': 'n1', 'labels': ['Customer'], 'props': {'customer_id': 'C0001'}},\n"
        "                                {'id': 'n2', 'labels': ['Account'], 'props': {'account_id': 'A0001'}}],\n"
        "                      'relationships': [{'id': 'r1', 'type': 'OWNS', 'start': 'n1', 'end': 'n2', 'props': {}}]},\n"
        "            'sources': [{'document_id': 'DOC001', 'title': 'PIX', 'text': 'trecho', 'score': 0.8}],\n"
        "            'entity_ids': ['C0001']}\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("BANKGRAPH_RETRIEVER", "fake_retrieval:answer")
    monkeypatch.chdir(ROOT)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert at.sidebar.selectbox[0].value.startswith("Etapa 5")
    at.text_area[0].input("Quais contas o cliente C0001 tem?")
    at.button[0].click().run()
    assert not at.exception, at.exception
    md = " ".join(m.value for m in at.markdown)
    assert "Resposta de teste para Quais contas o cliente C0001 tem?" in md
    assert any("MATCH (c:Customer)" in c.value for c in at.code)
    assert any(m.label == "Nós no subgrafo" and m.value == "2" for m in at.metric)


def _customer_record():
    return {"c": {"name": "Ana", "segment": "BASIC"},
            "contas_info": [{"account_id": "A0525", "tipo": "CHECKING", "status": "ACTIVE", "titularidade": "PRIMARY"}],
            "emprestimos_info": [{"loan_id": "L0041", "status": "ACTIVE", "valor_brl": 1000.0},
                                 {"loan_id": "L0099", "status": "PAID", "valor_brl": None}],
            "cartoes_info": [{"card_id": "CC0001", "bandeira": "VISA", "status": "ACTIVE"}]}


@pytest.mark.parametrize("question,ids", [
    ("Quais contas pertencem ao cliente C0208?", ["C0208", "A0525"]),
    ("Quais empréstimos do cliente C0208 estão ativos?", ["C0208", "L0041"]),
    ("Quais empréstimos o cliente C0208 tem?", ["C0208", "L0041", "L0099"]),
    ("Quais cartões o cliente C0208 possui?", ["C0208", "CC0001"]),
])
def test_customer_handler_focus(question, ids):
    res = StubRetriever([[_customer_record()]]).answer(question)
    assert res["entity_ids"] == ids
    assert res["answer"].startswith("**C0208** (Ana")


def test_run_uses_read_transaction_with_timeout():
    """Regressao: tx.run so aceita texto; o timeout vai pelo unit_of_work (neo4j.Query quebrava tudo)."""
    pytest.importorskip("neo4j")
    seen = {}

    class Tx:
        def run(self, query, params):
            assert isinstance(query, str), "tx.run recebe a consulta como texto"
            seen["params"] = params
            return iter([{"n": 1}])

    class Session:
        def __init__(self, **kw):
            seen["mode"] = kw.get("default_access_mode")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute_read(self, fn):
            seen["timeout"] = getattr(fn, "timeout", None)
            return fn(Tx())

    class Driver:
        def session(self, **kw):
            return Session(**kw)

    rows = BaselineRetriever(driver=Driver()).run("RETURN 1 AS n", {"x": 1})
    assert rows == [{"n": 1}] and seen["params"] == {"x": 1}
    assert seen["mode"] == "READ" and seen["timeout"] == 15
