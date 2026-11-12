"""Algoritmos de grafo: PageRank e deteccao de comunidades (Louvain) na rede de pagamentos.

Rede analisada (nao direcionada, ponderada):
  Cliente --(pagou N vezes)-- Estabelecimento     peso = numero de transacoes
  Cliente --(divide conta)--- Cliente             peso = JOINT_WEIGHT (vinculo forte: conta conjunta)

Resultados gravados no Neo4j:
  Customer.pagerank, Customer.community, Merchant.pagerank, Merchant.community
O caminho minimo entre clientes usa o shortestPath nativo do Cypher (template 'path_between_customers').

Uso (variaveis NEO4J_* definidas):
  python graph_algorithms.py                     # le do Neo4j, calcula e grava
  python graph_algorithms.py --dry-run           # calcula e mostra o resumo, sem gravar
  python graph_algorithms.py --from-csv --dry-run   # calcula a partir dos CSVs (sem Neo4j)
Sem plugin: usa networkx (Neo4j GDS nao e necessario). Louvain com semente fixa: resultado reproduzivel.
"""
import argparse
import os
from collections import Counter, defaultdict
from pathlib import Path

JOINT_WEIGHT = 5.0
SEED = 42
DATA = Path(__file__).parent / "BankGraph_AI_Dataset"


# ------------------------------------------------------------------ carga
def load_from_csv(data=DATA):
    import pandas as pd
    rd = lambda n: pd.read_csv(Path(data) / f"{n}.csv", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    tx, own = rd("transactions"), rd("account_owners")
    m = tx.merge(own, on="account_id")
    m["flag"] = (m.flagged == "True").astype(int)
    pay = m.groupby(["customer_id", "merchant_id"]).agg(n=("transaction_id", "count"), flagged=("flag", "sum")).reset_index()
    pairs = own.merge(own, on="account_id")
    pairs = pairs[pairs.customer_id_x < pairs.customer_id_y]
    return ([(r.customer_id, r.merchant_id, int(r.n), int(r.flagged)) for r in pay.itertuples()],
            [(r.customer_id_x, r.customer_id_y, r.account_id) for r in pairs.itertuples()])


def load_from_neo4j(session):
    pay = session.run("""MATCH (c:Customer)-[:OWNS]->(:Account)-[:SENT]->(t:Transaction)-[:PAID_TO]->(m:Merchant)
                         RETURN c.customer_id AS c, m.merchant_id AS m, count(t) AS n,
                                sum(CASE WHEN t.flagged THEN 1 ELSE 0 END) AS flagged""").values()
    joint = session.run("""MATCH (x:Customer)-[:OWNS]->(a:Account)<-[:OWNS]-(y:Customer)
                           WHERE x.customer_id < y.customer_id
                           RETURN x.customer_id, y.customer_id, a.account_id""").values()
    return [tuple(r) for r in pay], [tuple(r) for r in joint]


# ------------------------------------------------------------------ calculo
def build_graph(payments, joint):
    import networkx as nx
    g = nx.Graph()
    for c, m, n, _ in payments:
        g.add_node(c, kind="customer")
        g.add_node(m, kind="merchant")
        g.add_edge(c, m, weight=float(n))
    for x, y, _ in joint:
        g.add_node(x, kind="customer")
        g.add_node(y, kind="customer")
        w = g[x][y]["weight"] + JOINT_WEIGHT if g.has_edge(x, y) else JOINT_WEIGHT
        g.add_edge(x, y, weight=w)
    return g


def compute(payments, joint, resolution=1.0):
    import networkx as nx
    from networkx.algorithms.community import louvain_communities
    g = build_graph(payments, joint)
    pagerank = nx.pagerank(g, weight="weight")
    comms = louvain_communities(g, weight="weight", resolution=resolution, seed=SEED)
    comms = sorted(comms, key=lambda c: (-len(c), min(c)))          # numeracao estavel: maior comunidade = 0
    community = {n: i for i, c in enumerate(comms) for n in c}
    flagged_by_customer = Counter()
    for c, _, _, f in payments:
        flagged_by_customer[c] += f
    stats = defaultdict(lambda: {"clientes": 0, "estabelecimentos": 0, "sinalizadas": 0})
    for n, k in community.items():
        s = stats[k]
        if g.nodes[n]["kind"] == "customer":
            s["clientes"] += 1
            s["sinalizadas"] += flagged_by_customer[n]
        else:
            s["estabelecimentos"] += 1
    return {"graph": g, "pagerank": pagerank, "community": community, "stats": dict(stats),
            "modularity": nx.algorithms.community.modularity(g, comms, weight="weight")}


def summary(res, top=5):
    g, pr = res["graph"], res["pagerank"]
    merchants = sorted((n for n in g if g.nodes[n]["kind"] == "merchant"), key=lambda n: -pr[n])[:top]
    customers = sorted((n for n in g if g.nodes[n]["kind"] == "customer"), key=lambda n: -pr[n])[:top]
    lines = [f"Rede: {g.number_of_nodes()} nos, {g.number_of_edges()} arestas",
             f"PageRank - estabelecimentos mais centrais: " + ", ".join(f"{m} ({pr[m]:.4f})" for m in merchants),
             f"PageRank - clientes mais centrais: " + ", ".join(f"{c} ({pr[c]:.4f})" for c in customers),
             f"Louvain: {len(res['stats'])} comunidades, modularidade {res['modularity']:.3f}"]
    ranked = sorted(res["stats"].items(), key=lambda kv: -kv[1]["sinalizadas"])[:top]
    for k, s in ranked:
        lines.append(f"  comunidade {k}: {s['clientes']} clientes, {s['estabelecimentos']} estabelecimentos, "
                     f"{s['sinalizadas']} transacoes sinalizadas")
    return "\n".join(lines)


# ------------------------------------------------------------------ gravacao
def write(session, res):
    g = res["graph"]
    rows = [{"id": n, "pr": res["pagerank"][n], "comm": res["community"][n]} for n in g]
    cust = [r for r in rows if g.nodes[r["id"]]["kind"] == "customer"]
    merc = [r for r in rows if g.nodes[r["id"]]["kind"] == "merchant"]
    session.run("""UNWIND $rows AS r MATCH (c:Customer {customer_id: r.id})
                   SET c.pagerank = r.pr, c.community = r.comm""", rows=cust).consume()
    session.run("""UNWIND $rows AS r MATCH (m:Merchant {merchant_id: r.id})
                   SET m.pagerank = r.pr, m.community = r.comm""", rows=merc).consume()
    session.run("CREATE INDEX customer_community IF NOT EXISTS FOR (c:Customer) ON (c.community)").consume()
    session.run("CREATE INDEX merchant_community IF NOT EXISTS FOR (m:Merchant) ON (m.community)").consume()
    return len(cust), len(merc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="calcula e mostra o resumo, sem gravar")
    ap.add_argument("--from-csv", action="store_true", help="calcula a partir dos CSVs (sem Neo4j)")
    ap.add_argument("--resolution", type=float, default=1.0, help="Louvain: maior = comunidades menores")
    a = ap.parse_args()
    if a.from_csv:
        payments, joint = load_from_csv()
        res = compute(payments, joint, a.resolution)
        print(summary(res))
        if not a.dry_run:
            print("--from-csv so calcula; para gravar, rode sem --from-csv.")
        return
    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with drv.session() as s:
        payments, joint = load_from_neo4j(s)
        res = compute(payments, joint, a.resolution)
        print(summary(res))
        if a.dry_run:
            print("dry-run: nada foi gravado.")
        else:
            nc, nm = write(s, res)
            print(f"Gravado: pagerank e community em {nc} clientes e {nm} estabelecimentos.")
    drv.close()


if __name__ == "__main__":
    main()
