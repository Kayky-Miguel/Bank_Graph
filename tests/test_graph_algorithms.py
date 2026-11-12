"""Algoritmos de grafo (PageRank e Louvain) calculados a partir dos CSVs, sem Neo4j."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("networkx")

from graph_algorithms import compute, load_from_csv, write  # noqa: E402


@pytest.fixture(scope="module")
def res():
    return compute(*load_from_csv())


def test_network_shape(res):
    g = res["graph"]
    kinds = {g.nodes[n]["kind"] for n in g}
    assert kinds == {"customer", "merchant"}
    assert sum(1 for n in g if g.nodes[n]["kind"] == "merchant") == 150


def test_pagerank_is_distribution_and_m0001_is_central(res):
    pr = res["pagerank"]
    assert abs(sum(pr.values()) - 1.0) < 1e-6
    merchants = sorted((n for n in res["graph"] if n.startswith("M")), key=lambda n: -pr[n])
    assert merchants[0] == "M0001"            # o mesmo estabelecimento que lidera a concentracao de pagamentos


def test_louvain_is_reproducible_and_covers_all_nodes(res):
    again = compute(*load_from_csv())
    assert again["community"] == res["community"]                 # semente fixa
    assert set(res["community"]) == set(res["graph"].nodes)
    # contagem por titular: transacao sinalizada de conta conjunta conta para cada dono (100 transacoes -> 101 pares)
    payments, _ = load_from_csv()
    assert sum(s["sinalizadas"] for s in res["stats"].values()) == sum(f for _, _, _, f in payments) == 101
    assert res["modularity"] > 0


def test_write_sends_customers_and_merchants(res):
    calls = []

    class S:
        def run(self, q, **kw):
            calls.append((q, kw))

            class R:
                def consume(self):
                    return None
            return R()

    nc, nm = write(S(), res)
    assert (nc, nm) == (500, 150)
    assert any("Customer" in q and "pagerank" in q for q, _ in calls)
    assert any("Merchant" in q and "community" in q for q, _ in calls)
