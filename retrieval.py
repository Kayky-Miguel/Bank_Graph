"""Adaptador: liga a Etapa 5 (graphrag_pipeline.answer) a interface (app.py) e a avaliacao (evaluate_qa.py).

A interface e a avaliacao procuram `retrieval:answer(question)` e esperam o contrato de ui_backend.py.
Este arquivo so traduz; a logica de recuperacao continua toda em graphrag_pipeline.py.

Provedor do LLM: variavel LLM_PROVIDER ("openai" ou "mock"). Se nao for definida, usa "openai" quando
OPENAI_API_KEY existe e "mock" caso contrario. Com "mock" as respostas sao simuladas: servem para testar
o fluxo, NAO para medir qualidade.
"""
import json
import os
import re

import graphrag_pipeline as G

PROVIDER = os.environ.get("LLM_PROVIDER") or ("openai" if os.environ.get("OPENAI_API_KEY") else "mock")
MAX_GRAPH_IDS = 150            # limite de nos buscados para desenhar o subgrafo

# prefixo do ID -> (label, propriedade). Prefixos longos primeiro (CC antes de C, AL antes de A...).
ID_KINDS = [("DOC", "Document", "document_id"), ("CC", "Card", "card_id"), ("CP", "Complaint", "complaint_id"),
            ("AL", "Alert", "alert_id"), ("C", "Customer", "customer_id"), ("A", "Account", "account_id"),
            ("T", "Transaction", "transaction_id"), ("L", "Loan", "loan_id"), ("M", "Merchant", "merchant_id"),
            ("B", "Branch", "branch_id"), ("E", "Employee", "employee_id"), ("R", "BankingRule", "rule_id")]
_ID_RE = re.compile(r"\b(?:DOC\d{3}|CC\d{4}|CP\d{5}|AL\d{5}|C\d{4}|A\d{4}|T\d{7}|L\d{4}|M\d{4}|B\d{3}|E\d{4}|R\d{3})\b")

_driver = None


def driver():
    global _driver
    if _driver is None:
        _driver = G.get_driver()
    return _driver


def group_ids(ids):
    """{(label, prop): [ids]} a partir dos prefixos."""
    out = {}
    for i in ids:
        for prefix, label, prop in ID_KINDS:
            if i.startswith(prefix) and i[len(prefix):].isdigit():
                out.setdefault((label, prop), []).append(i)
                break
    return out


def fetch_subgraph(session, ids):
    """Nos das evidencias + relacionamentos diretos entre eles (para a visualizacao)."""
    records = []
    for (label, prop), vals in group_ids(ids).items():
        # label e prop vem da tabela fixa ID_KINDS, nunca do usuario/LLM
        records += session.run(f"MATCH (n:{label}) WHERE n.{prop} IN $ids RETURN n", ids=vals).values()
    eids = [r[0].element_id for r in records]
    if eids:
        records += session.run("""MATCH (a)-[r]->(b) WHERE elementId(a) IN $e AND elementId(b) IN $e
                                  RETURN r LIMIT 500""", e=eids).values()
    return records


def evidence_ids(out):
    """Todos os IDs presentes nas evidencias (linhas do grafo, regras, documentos).
    Usa o padrao completo de IDs: o de graphrag_pipeline nao reconhece cartoes (CC) nem reclamacoes (CP)."""
    blob = json.dumps([out.get("graph_rows"), out.get("rules"), out.get("documents")], default=str, ensure_ascii=False)
    return set(_ID_RE.findall(blob))


def to_contract(out, records=None):
    """Saida de graphrag_pipeline.answer -> contrato de ui_backend.normalize_result."""
    sources = []
    for h in out.get("documents") or []:
        sources.append({"document_id": h.get("id"), "title": h.get("title"), "section": h.get("section"),
                        "page": h.get("page"), "score": h.get("score"), "label": h.get("label")})
    seen = {s["document_id"] for s in sources}
    for r in out.get("rules") or []:
        if r.get("documento") and r["documento"] not in seen:
            seen.add(r["documento"])
            sources.append({"document_id": r["documento"], "title": r.get("titulo"), "section": r.get("secao"),
                            "page": r.get("pagina"), "text": r.get("descricao"), "rule_id": r.get("regra")})
    answer_text = out.get("answer") or ""
    evidence = evidence_ids(out)
    notes = [f"Etapa 5 (graphrag_pipeline), LLM: {PROVIDER}" + (" - respostas SIMULADAS" if PROVIDER == "mock" else "")]
    notes += [str(e) for e in out.get("errors") or []]
    queries = []
    if out.get("cypher"):
        queries.append({"cypher": out["cypher"], "params": out.get("params") or {},
                        "rows": len(out.get("graph_rows") or []), "purpose": out.get("query_origin") or ""})
    return {
        "answer": answer_text,
        "insufficient_evidence": bool(out.get("abstained")),
        "confidence": out.get("confidence"),
        "confidence_reason": "heuristica da Etapa 5 (nao e probabilidade)",
        "queries": queries,
        "rows": list(out.get("graph_rows") or []) + [{k: v for k, v in r.items() if k != "fatos"} for r in out.get("rules") or []],
        "sources": sources,
        # entidades CITADAS na resposta (as que a resposta afirma), destacadas no subgrafo
        "entity_ids": sorted(set(_ID_RE.findall(answer_text)) & evidence),
        "records": records or [],
        "notes": notes,
    }


def answer(question):
    drv = driver()
    out = G.answer(question, drv, PROVIDER)
    ids = sorted(evidence_ids(out))[:MAX_GRAPH_IDS]
    try:
        with drv.session() as s:
            records = fetch_subgraph(s, ids)
    except Exception as e:                       # sem subgrafo, mas a resposta continua valida
        records = []
        out.setdefault("errors", []).append(f"subgrafo: {e}")
    return to_contract(out, records)
