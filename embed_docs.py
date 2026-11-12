"""Etapa 4 / Passo 1 - embeddings dos documentos e regras, gravados no Neo4j.

Uso (mesmas variaveis NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD do ingest.py):
  pip install sentence-transformers neo4j
  python embed_docs.py                         # gera e grava embeddings
  python embed_docs.py --query "limite do PIX" # testa a busca vetorial
O indice vetorial (schema.cypher) usa 384 dimensoes: o modelo padrao tem 384.
Se trocar o modelo, ajuste vector.dimensions no schema.cypher e recrie o indice.
"""
import argparse, os

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"   # multilingue (PT), 384 dim
EXPECTED_DIM = 384

def connect():
    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    drv.verify_connectivity()
    return drv

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("EMBED_MODEL", DEFAULT_MODEL))
    ap.add_argument("--query", help="so executa uma busca vetorial de teste com este texto")
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(a.model)          # 1a vez: baixa o modelo (algumas centenas de MB)
    dim = model.get_sentence_embedding_dimension()
    if dim != EXPECTED_DIM:
        raise SystemExit(f"O modelo gera {dim} dimensoes, mas o indice espera {EXPECTED_DIM}. Ajuste o schema.cypher.")

    drv = connect()
    with drv.session() as s:
        if a.query:
            vec = model.encode(a.query, normalize_embeddings=True).tolist()
            res = s.run("""CALL db.index.vector.queryNodes('document_embedding', $k, $vec) YIELD node, score
                           RETURN node.document_id AS id, node.title AS title, node.section AS sec,
                                  node.page AS page, score, node.text AS text""", k=a.k, vec=vec)
            for r in res:
                print(f"{r['score']:.3f}  {r['id']}  {r['title']} (sec {r['sec']}, p.{r['page']})\n       {r['text'][:110]}")
            return

        docs = s.run("MATCH (d:Document) RETURN d.document_id AS id, d.title AS title, d.text AS text").data()
        # embedding do titulo + texto: o titulo traz o tema da regra
        vecs = model.encode([f"{d['title']}. {d['text']}" for d in docs], normalize_embeddings=True)
        for d, v in zip(docs, vecs):
            s.run("MATCH (n:Document {document_id:$id}) CALL db.create.setNodeVectorProperty(n, 'embedding', $v)",
                  id=d["id"], v=v.tolist()).consume()
        print(f"{len(docs)} documentos com embedding")

        rules = s.run("MATCH (r:BankingRule) RETURN r.rule_id AS id, r.rule_name AS name, r.description AS text").data()
        vecs = model.encode([f"{r['name']}. {r['text']}" for r in rules], normalize_embeddings=True)
        for r, v in zip(rules, vecs):
            s.run("MATCH (n:BankingRule {rule_id:$id}) CALL db.create.setNodeVectorProperty(n, 'embedding', $v)",
                  id=r["id"], v=v.tolist()).consume()
        print(f"{len(rules)} regras com embedding")
    drv.close()

if __name__ == "__main__":
    main()
