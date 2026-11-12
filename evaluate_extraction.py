"""Etapa 4 / Passo 6 - precisao, recall e F1 da extracao (NER e RE) contra um gabarito anotado a mao.

Uso:
  python evaluate_extraction.py                       # le gold_annotations.json e extraction_results.json
  python evaluate_extraction.py --gold outro.json --pred extraction_results.json
Avalia apenas os documentos que estao no gabarito. Comparacao por nome normalizado (sem acento/caixa).
"""
import argparse, json
from pathlib import Path
from extract_entities import normalize

def ent_set(items):
    return {(e["type"], normalize(e["name"])) for e in items}

def rel_set(items):
    return {(normalize(r["source"]), r["type"], normalize(r["target"])) for r in items}

def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="gold_annotations.json")
    ap.add_argument("--pred", default="extraction_results.json")
    a = ap.parse_args()
    gold = json.loads(Path(a.gold).read_text(encoding="utf-8"))
    gold = {k: v for k, v in gold.items() if not k.startswith("_")}
    pred = json.loads(Path(a.pred).read_text(encoding="utf-8"))

    tot = {"ent": [0, 0, 0], "rel": [0, 0, 0]}
    for doc, g in gold.items():
        if doc not in pred:
            print(f"{doc}: sem predicao (rode extract_entities.py)"); continue
        p = pred[doc]
        for kind, gs, ps in (("ent", ent_set(g["entities"]), ent_set(p["entities"])),
                             ("rel", rel_set(g["relations"]), rel_set(p["relations"]))):
            tp, fp, fn = len(gs & ps), len(ps - gs), len(gs - ps)
            for i, v in enumerate((tp, fp, fn)):
                tot[kind][i] += v
            if fp or fn:
                print(f"{doc} [{kind}] FALSOS POSITIVOS: {sorted(ps - gs)}  FALTARAM: {sorted(gs - ps)}")
    print(f"\nDocumentos avaliados: {len(gold)}")
    for kind, label in (("ent", "Entidades (NER)"), ("rel", "Relacoes (RE)")):
        p, r, f = prf(*tot[kind])
        print(f"{label:18} precisao={p:.2f}  recall={r:.2f}  F1={f:.2f}   (TP={tot[kind][0]} FP={tot[kind][1]} FN={tot[kind][2]})")

if __name__ == "__main__":
    main()
