"""Carrega extraction_results.json (saida ja validada da Etapa 4) no Neo4j, SEM chamar LLM e sem chave de API.
Reaproveita as funcoes do extract_entities.py (mesmas chaves de entidade e mesmo write_graph).
Uso (na pasta do repositorio, com NEO4J_URI/USER/PASSWORD definidos):
  python load_extraction_results.py            # grava no Neo4j
  python load_extraction_results.py --dry-run  # so confere e mostra as contagens
"""
import json, sys
from collections import defaultdict
from pathlib import Path
import extract_entities as E

def build(results):
    entities, relations, mentions = {}, defaultdict(set), defaultdict(set)
    for doc_id, r in results.items():
        local = []                                     # (chave, nome, tipo) das entidades deste documento
        for e in r["entities"]:
            k = E.key_of(e["type"], e["name"])
            entities.setdefault(k, {"name": e["name"], "type": e["type"]})
            mentions[doc_id].add(k); local.append((k, e["name"], e["type"]))
        for rel in r["relations"]:
            pairs = E.RELATIONS[rel["type"]]
            src = [k for k, n, t in local if E.normalize(n) == E.normalize(rel["source"]) and any(t == a for a, _ in pairs)]
            dst = [k for k, n, t in local if E.normalize(n) == E.normalize(rel["target"]) and any(t == b for _, b in pairs)]
            if not src or not dst:
                raise SystemExit(f"{doc_id}: nao consegui resolver a relacao {rel}")
            relations[(src[0], rel["type"], dst[0])].add(doc_id)
    return entities, relations, mentions

if __name__ == "__main__":
    results = json.loads(Path("extraction_results.json").read_text(encoding="utf-8"))
    entities, relations, mentions = build(results)
    from collections import Counter
    print(f"{len(results)} documentos | {len(entities)} entidades {dict(Counter(v['type'] for v in entities.values()))} | {len(relations)} relacoes distintas")
    if "--dry-run" in sys.argv:
        print("dry-run: nada foi gravado."); sys.exit()
    E.write_graph(mentions, entities, relations)
    print("Gravado no Neo4j.")
