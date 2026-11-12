"""Adaptador Etapa 5 -> contrato da interface/avaliacao (sem Neo4j e sem LLM)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("neo4j")

import retrieval  # noqa: E402
from ui_backend import normalize_result  # noqa: E402

OUT = {  # formato devolvido por graphrag_pipeline.answer
    "answer": "C0208 tem o emprestimo ativo L0041 e o cartao CC0407. C9999 tambem.",
    "abstained": False, "cypher": "MATCH (c:Customer) RETURN c LIMIT 50", "params": {"ref": "2026-11-10"},
    "query_origin": "template:customer_accounts",
    "graph_rows": [{"cliente": "C0208", "emprestimo": "L0041", "cartao": "CC0407"}],
    "documents": [{"id": "DOC003", "label": "Document", "title": "Empréstimo Pessoal - Documento 03",
                   "section": "1", "page": 2, "score": 0.8}],
    "rules": [{"documento": "DOC013", "titulo": "Empréstimo Pessoal - Documento 13", "secao": "1", "pagina": 3,
               "regra": "R013", "descricao": "prazo de 6 a 60 parcelas", "tema": "Empréstimo Pessoal", "fatos": []}],
    "entity_ids": ["C0208", "L0041"], "confidence": "alta", "errors": ["aviso x"], "latency_s": 1.2,
}


def test_to_contract_maps_fields():
    res = normalize_result(retrieval.to_contract(OUT), "q")
    assert res["answer"].startswith("C0208") and not res["insufficient_evidence"]
    assert res["queries"][0]["purpose"] == "template:customer_accounts" and res["queries"][0]["rows"] == 1
    assert [s["document_id"] for s in res["sources"]] == ["DOC003", "DOC013"]
    # citados na resposta E presentes nas evidencias; CC0407 entra (o regex do pipeline nao reconhece CC);
    # C9999 nao esta nas evidencias, entao nao vira entidade citada
    assert res["entity_ids"] == ["C0208", "CC0407", "L0041"]
    assert "aviso x" in res["notes"]


def test_abstention_maps_to_insufficient_evidence():
    res = normalize_result(retrieval.to_contract({"answer": "Não há evidência suficiente.", "abstained": True}), "q")
    assert res["insufficient_evidence"] and res["queries"] == [] and res["entity_ids"] == []


def test_group_ids_by_prefix():
    g = retrieval.group_ids(["CC0001", "C0001", "AL00001", "A0001", "DOC001", "R001", "T0000001", "XYZ"])
    assert g[("Card", "card_id")] == ["CC0001"] and g[("Customer", "customer_id")] == ["C0001"]
    assert g[("Alert", "alert_id")] == ["AL00001"] and g[("Account", "account_id")] == ["A0001"]
    assert g[("Document", "document_id")] == ["DOC001"] and g[("BankingRule", "rule_id")] == ["R001"]
    assert sum(len(v) for v in g.values()) == 7


def test_ui_finds_etapa5_by_default(monkeypatch):
    from ui_backend import load_external
    monkeypatch.delenv("BANKGRAPH_RETRIEVER", raising=False)
    spec, fn = load_external()
    assert spec == "retrieval:answer" and fn is retrieval.answer
