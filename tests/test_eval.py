"""Testes da Etapa 7 sem Neo4j: gabarito (contra os valores do README) e metricas.

  python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluate_qa import (QUESTIONS, build_gold, load_data, report, run_backend, score,  # noqa: E402
                         summarize)
from ui_backend import BaselineRetriever, normalize_result  # noqa: E402


@pytest.fixture(scope="module")
def gold():
    return build_gold(load_data())


def test_gold_matches_readme_values(gold):
    # README: 7 clientes com transacao sinalizada em 30 dias; 3 com emprestimo ativo
    central = gold["A01"]["gold_ids"]
    assert len([i for i in central if i.startswith("C")]) == 7
    assert gold["I04"]["gold_ids"] == ["C0208", "C0234", "C0410"]
    # README: relacao indireta com janela de 365 dias -> 4 clientes
    assert len(gold["A02"]["gold_ids"]) == 4
    # README: M0001 lidera a concentracao de pagamentos
    assert "M0001" in gold["I03"]["gold_ids"]
    # 10 temas x 3 versoes: cada pergunta de regra espera 3 regras
    for q in ("A03", "A04", "A05", "A06"):
        assert len(gold[q]["gold_ids"]) == 3


def test_question_set_shape():
    kinds = {q["kind"] for q in QUESTIONS}
    assert {"answerable", "unanswerable", "ambiguous", "out_of_domain"} <= kinds
    assert 15 <= len(QUESTIONS) <= 25                     # plano: 15 a 25 perguntas
    assert len({q["id"] for q in QUESTIONS}) == len(QUESTIONS)


def _res(**kw):
    return normalize_result(kw, "q")


def test_score_answerable_precision_recall(gold):
    q = gold["I04"]
    s = score(q, _res(answer="C0208 e C0234 e C0159", entity_ids=["C0208", "C0234", "C0159", "T0001050"],
                      rows=[{"c": "C0208"}, {"c": "C0234"}, {"c": "C0159"}]))
    assert s["recall"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["precision"] == pytest.approx(2 / 3, abs=1e-3)       # T0001050 nao conta: tipo diferente
    assert not s["correct"] and s["missing"] == ["C0410"]
    assert s["unsupported_ids"] == []


def test_score_flags_unsupported_ids(gold):
    s = score(gold["B01"], _res(answer="Contas A0525 e A0689", entity_ids=[], rows=[{"a": "A0525"}]))
    assert s["unsupported_ids"] == ["A0689"] and s["recall"] == 1.0


def test_score_abstention_and_must_say(gold):
    assert score(gold["O01"], _res(answer="x", insufficient_evidence=True))["correct"]
    assert not score(gold["O01"], _res(answer="Faz sol."))["correct"]
    ok = score(gold["U01"], _res(answer="Não. Alerta sintético não comprova fraude."))
    assert ok["correct"] and ok["must_say_ok"]
    cpf = score(gold["U03"], _res(answer="O CPF é 123.456.789-00", insufficient_evidence=True))
    assert not cpf["correct"]


def test_oracle_backend_gets_everything_right(gold):
    def oracle(question):
        q = next(g for g in gold.values() if g["question"] == question)
        if q["kind"] != "answerable":
            return {"answer": "Nao ha evidencia; alerta nao comprova fraude.", "insufficient_evidence": True}
        ids = q["gold_ids"]
        return {"answer": "ok " + " ".join(ids) + " R$ 2.000", "entity_ids": ids, "rows": [{"ids": ids}],
                "sources": [{"title": (q.get("topic") or "x") + " - Documento 01"}]}

    scores, raw = run_backend(oracle, gold)
    summ = summarize(scores)
    assert summ["acuracia"] == 1.0 and summ["recall_ids"] == 1.0 and summ["respostas_com_id_sem_suporte"] == 0.0
    md = report(gold, {"oraculo": {"summary": summ, "scores": scores}})
    assert "| Acuracia geral | 1.00 |" in md


def test_backend_exception_is_recorded_not_raised(gold):
    def broken(question):
        raise RuntimeError("neo4j fora do ar")

    scores, _ = run_backend(broken, {"B01": gold["B01"]})
    assert scores[0]["error"].startswith("RuntimeError") and not scores[0]["correct"]


@pytest.mark.parametrize("qid,intent", [("B02", "cliente"), ("B04", "cliente"), ("I04", "sinalizadas"),
                                        ("A01", "sinalizadas"), ("A02", "indireta"), ("I02", "conjunta"),
                                        ("A04", "documentos"), ("U02", "cliente")])
def test_baseline_routes_eval_questions(gold, qid, intent):
    assert BaselineRetriever(driver=object()).route(gold[qid]["question"])[0] == intent


# ---------------- analise de erros da extracao
from evaluate_extraction import analyze_doc  # noqa: E402


def test_extraction_error_categories():
    gold = {("Obligation", "registrar justificativa data e responsavel"), ("Condition", "mais de um titular"),
            ("Limit", "r 2 000 por dia")}
    pred = {("Obligation", "justificativa"), ("Obligation", "data"), ("Obligation", "responsavel"),
            ("Limit", "r 2 000"), ("Action", "bloqueio")}
    r = analyze_doc(gold, pred, "ent")
    cats = sorted(e[0] for e in r["events"])
    assert cats == ["enumeracao separada", "extra (fora do gabarito)", "omissao", "variacao de nome"]
    assert r["gold_relaxed"] == 2 and r["pred_relaxed"] == 4 and r["tp_strict"] == 0


def test_extraction_relation_needs_same_source():
    gold = {("bloqueio preventivo", "MUST_RECORD", "data e responsavel")}
    pred = {("outra regra", "MUST_RECORD", "data"), ("outra regra", "MUST_RECORD", "responsavel")}
    r = analyze_doc(gold, pred, "rel")
    assert r["gold_relaxed"] == 0


def test_load_results_rebuilds_full_extraction():
    """--from-results: grava no grafo a extracao validada sem LLM; nada pode se perder."""
    import json
    from extract_entities import load_results
    path = Path(__file__).resolve().parents[1] / "extraction_results.json"
    src = json.loads(path.read_text(encoding="utf-8"))
    got = load_results(path)
    assert set(got) == set(src)
    for doc in src:
        assert len(got[doc]["entities"]) == len(src[doc]["entities"])
        assert len(got[doc]["relations"]) == len(src[doc]["relations"])
        assert all(":" in r["source"] and ":" in r["target"] for r in got[doc]["relations"])
