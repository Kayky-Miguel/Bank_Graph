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

# ---------------- Etapa 7: analise de erros (classifica cada divergencia) ----------------
STOP = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "por", "ao", "em", "para", "com", "no", "na", "r"}


def toks(s):
    return {t for t in normalize(s).split() if t not in STOP}


def similar(a, b):
    """mesmo conteudo com nome diferente: um contido no outro, ou Jaccard >= 0,5."""
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta or len(ta & tb) / len(ta | tb) >= 0.5


def analyze_doc(gold_items, pred_items, kind):
    """Casa gabarito x predicao em 3 passos (exato, enumeracao separada, variacao de nome) e classifica o resto.
    Itens de entidade: (tipo, nome). Itens de relacao: (origem, tipo, destino)."""
    if kind == "ent":
        typ, txt = (lambda x: x[0]), (lambda x: x[1])
        same_head = lambda g, p: True
    else:
        typ, txt = (lambda x: x[1]), (lambda x: x[2])
        same_head = lambda g, p: similar(g[0], p[0])
    gold, pred = set(gold_items), set(pred_items)
    events, matched_g, matched_p, wrong_type = [], set(), set(), set()
    for g in gold & pred:
        matched_g.add(g); matched_p.add(g)
    for g in sorted(gold - matched_g):
        free = [p for p in pred - matched_p if typ(p) == typ(g) and same_head(g, p)]
        parts = [p for p in free if toks(txt(p)) and toks(txt(p)) <= toks(txt(g))]
        cover = set().union(*[toks(txt(p)) for p in parts]) if parts else set()
        if len(parts) >= 2 and len(cover) >= 0.6 * len(toks(txt(g))):
            matched_g.add(g); matched_p.update(parts)
            events.append(("enumeracao separada", g, sorted(parts)))
            continue
        sim = [p for p in free if similar(txt(g), txt(p))]
        if sim:
            matched_g.add(g); matched_p.add(sim[0])
            events.append(("variacao de nome", g, [sim[0]]))
    for g in sorted(gold - matched_g):
        other = [p for p in pred - matched_p - wrong_type if typ(p) != typ(g) and similar(txt(g), txt(p))]
        if other:
            wrong_type.add(other[0])          # achou o conceito, mas com tipo errado: continua sendo erro
            events.append(("tipo/relacao diferente", g, [other[0]]))
        else:
            events.append(("omissao", g, []))
    for p in sorted(pred - matched_p - wrong_type):
        events.append(("extra (fora do gabarito)", None, [p]))
    return {"tp_strict": len(gold & pred), "gold": len(gold), "pred": len(pred),
            "gold_relaxed": len(matched_g), "pred_relaxed": len(matched_p),
            "events": events}


def analysis(gold, pred, out_path):
    from collections import Counter
    tot = {k: Counter() for k in ("ent", "rel")}
    cats = {k: Counter() for k in ("ent", "rel")}
    lines = ["# Analise de erros da extracao (NER/RE)", "",
             "Gerado por `python evaluate_extraction.py --analysis`. Cada divergencia entre o gabarito e a extracao "
             "foi classificada automaticamente:", "",
             "- **enumeracao separada**: o gabarito tem um item e o LLM separou em varios (ex.: \"justificativa, data e responsavel\" -> 3 itens). Conteudo correto, granularidade diferente.",
             "- **variacao de nome**: mesmo conceito com nome diferente (um contido no outro ou sobreposicao >= 50% das palavras).",
             "- **tipo/relacao diferente**: conceito encontrado, mas com tipo de entidade ou relacao errado. Erro real.",
             "- **omissao**: item do gabarito que nao foi extraido. Erro real.",
             "- **extra (fora do gabarito)**: item extraido sem correspondente no gabarito. Pode ser erro ou item valido nao anotado.", ""]
    detail = []
    for doc, g in gold.items():
        if doc not in pred:
            continue
        p = pred[doc]
        for kind, gs, ps in (("ent", ent_set(g["entities"]), ent_set(p["entities"])),
                             ("rel", rel_set(g["relations"]), rel_set(p["relations"]))):
            r = analyze_doc(gs, ps, kind)
            for k in ("tp_strict", "gold", "pred", "gold_relaxed", "pred_relaxed"):
                tot[kind][k] += r[k]
            for cat, gi, pi in r["events"]:
                cats[kind][cat] += 1
                fmt = lambda x: " / ".join(x) if isinstance(x, tuple) else str(x)
                detail.append(f"| {doc} | {kind.upper()} | {cat} | {fmt(gi) if gi else '-'} | {'; '.join(fmt(x) for x in pi) or '-'} |")
    lines += ["## Metricas", "", "| | Precisao | Recall | F1 |", "|---|---|---|---|"]
    for kind, label in (("ent", "Entidades (NER)"), ("rel", "Relacoes (RE)")):
        t = tot[kind]
        ps, rs, fs = prf(t["tp_strict"], t["pred"] - t["tp_strict"], t["gold"] - t["tp_strict"])
        pr = t["pred_relaxed"] / t["pred"] if t["pred"] else 0
        rr = t["gold_relaxed"] / t["gold"] if t["gold"] else 0
        fr = 2 * pr * rr / (pr + rr) if pr + rr else 0
        lines.append(f"| {label}, estrita | {ps:.2f} | {rs:.2f} | {fs:.2f} |")
        lines.append(f"| {label}, relaxada | {pr:.2f} | {rr:.2f} | {fr:.2f} |")
    lines += ["", "A relaxada aceita enumeracao separada e variacao de nome como acerto; tipo errado, omissao e extra continuam erro.", "",
              "## Divergencias por categoria", "", "| Categoria | Entidades | Relacoes |", "|---|---|---|"]
    for cat in ("enumeracao separada", "variacao de nome", "tipo/relacao diferente", "omissao", "extra (fora do gabarito)"):
        lines.append(f"| {cat} | {cats['ent'][cat]} | {cats['rel'][cat]} |")
    lines += ["", "## Detalhe", "", "| Doc | Tipo | Categoria | Gabarito | Extraido |", "|---|---|---|---|---|"] + detail
    lines += ["", "## Limitacoes", "",
              "- O gabarito cobre DOC001-DOC010 (um documento por tema), anotado por uma pessoa so; sem concordancia entre anotadores.",
              "- Os 30 documentos sao 10 textos identicos em 3 versoes. A extracao dos splits dev/test e igual a do train, "
              "entao nao ha avaliacao independente por split.",
              "- A classificacao das divergencias e heuristica (sobreposicao de palavras); confira o detalhe acima."]
    Path(out_path).parent.mkdir(exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nAnalise de erros: {out_path}")
    for kind in ("ent", "rel"):
        print(f"  {kind.upper()}: " + ", ".join(f"{c}={n}" for c, n in cats[kind].items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="gold_annotations.json")
    ap.add_argument("--pred", default="extraction_results.json")
    ap.add_argument("--analysis", action="store_true", help="classifica os erros e grava evaluation/extraction_errors.md")
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
    if a.analysis:
        analysis(gold, pred, Path(__file__).parent / "evaluation" / "extraction_errors.md")

if __name__ == "__main__":
    main()
