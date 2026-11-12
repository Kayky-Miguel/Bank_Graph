"""Etapa 6 - conversao de resultados do Neo4j em subgrafo e renderizacao com PyVis.

collect_graph(valores)  percorre qualquer coisa que o driver devolve (Node, Relationship,
                        Path, listas, dicts, Records) e monta {"nodes": [...], "relationships": [...]}.
render_html(grafo)      gera o HTML interativo (vis-network) para st.components.v1.html.

Usa "duck typing" para nao exigir o pacote neo4j nos testes.
"""
import html
import json

# propriedade usada como legenda de cada label (chave de negocio)
CAPTION_KEY = {
    "Customer": "customer_id", "Account": "account_id", "Transaction": "transaction_id",
    "Loan": "loan_id", "Card": "card_id", "Merchant": "merchant_id", "Branch": "branch_id",
    "Employee": "employee_id", "Alert": "alert_id", "Complaint": "complaint_id",
    "Document": "document_id", "BankingRule": "rule_id", "Entity": "name",
}
# cores por label (paleta neutra, legivel em fundo claro e escuro)
COLORS = {
    "Customer": "#4C78A8", "Account": "#72B7B2", "Transaction": "#F58518", "Loan": "#B279A2",
    "Card": "#9D755D", "Merchant": "#54A24B", "Branch": "#BAB0AC", "Employee": "#BAB0AC",
    "Alert": "#E45756", "Complaint": "#FF9DA6", "Document": "#EECA3B", "BankingRule": "#D4A017",
    "Entity": "#79706E",
}
HIDDEN_PROPS = {"embedding"}           # vetores de 384 posicoes nao interessam na tela
MAX_TEXT = 160


def _is_node(v):
    return hasattr(v, "labels") and hasattr(v, "element_id")


def _is_rel(v):
    return hasattr(v, "start_node") and hasattr(v, "end_node") and hasattr(v, "type")


def _is_path(v):
    return hasattr(v, "nodes") and hasattr(v, "relationships") and not _is_node(v)


def _props(entity):
    out = {}
    for k, v in dict(entity).items():
        if k in HIDDEN_PROPS:
            continue
        # date/datetime do driver viram texto ISO
        out[k] = v.iso_format() if hasattr(v, "iso_format") else (str(v) if not isinstance(v, (int, float, bool, str, list, type(None))) else v)
    return out


def main_label(labels):
    """Label mais especifico para legenda/cor (Entity vem por ultimo: RuleTopic:Entity -> RuleTopic)."""
    labels = list(labels)
    for lb in labels:
        if lb != "Entity":
            return lb
    return labels[0] if labels else "?"


def caption(node):
    labels = node["labels"]
    props = node["props"]
    for lb in labels:
        key = CAPTION_KEY.get(lb)
        if key and props.get(key) is not None:
            text = str(props[key])
            return text if len(text) <= 28 else text[:26] + "…"
    if "Entity" in labels and props.get("name"):
        return str(props["name"])[:28]
    return main_label(labels)


def collect_graph(*values, graph=None):
    """Acumula nos e relacoes de quaisquer valores retornados pelo driver."""
    g = graph if graph is not None else {"nodes": [], "relationships": []}
    seen_n = {n["id"] for n in g["nodes"]}
    seen_r = {r["id"] for r in g["relationships"]}

    def add_node(n):
        if n is None or n.element_id in seen_n:
            return
        seen_n.add(n.element_id)
        g["nodes"].append({"id": n.element_id, "labels": sorted(n.labels), "props": _props(n)})

    def add_rel(r):
        if r is None or r.element_id in seen_r:
            return
        add_node(r.start_node)
        add_node(r.end_node)
        seen_r.add(r.element_id)
        g["relationships"].append({"id": r.element_id, "type": r.type, "start": r.start_node.element_id,
                                   "end": r.end_node.element_id, "props": _props(r)})

    def walk(v):
        if v is None:
            return
        if _is_path(v):
            for n in v.nodes:
                add_node(n)
            for r in v.relationships:
                add_rel(r)
        elif _is_rel(v):
            add_rel(v)
        elif _is_node(v):
            add_node(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif hasattr(v, "values") and callable(v.values) and not isinstance(v, (str, bytes)):  # neo4j.Record
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple, set)):
            for x in v:
                walk(x)

    for v in values:
        walk(v)
    return g


def _tooltip(node_or_rel, head):
    lines = [head]
    for k, v in node_or_rel["props"].items():
        s = str(v)
        lines.append(f"{k}: {s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + '…'}")
    return "\n".join(lines)


def render_html(graph, highlight=(), height=560, physics=True):
    """HTML autocontido com a visualizacao do subgrafo (PyVis / vis-network)."""
    from pyvis.network import Network

    net = Network(height=f"{height}px", width="100%", directed=True, cdn_resources="remote",
                  bgcolor="#ffffff", font_color="#222222")
    highlight = set(highlight)
    for n in graph["nodes"]:
        lb = main_label(n["labels"])
        hit = n["id"] in highlight or caption(n) in highlight
        net.add_node(n["id"], label=caption(n), title=_tooltip(n, ":".join(n["labels"])),
                     color={"background": COLORS.get(lb, "#999999"),
                            "border": "#111111" if hit else COLORS.get(lb, "#999999")},
                     borderWidth=4 if hit else 1, size=26 if hit else 18, group=lb)
    for r in graph["relationships"]:
        net.add_edge(r["start"], r["end"], label=r["type"], title=_tooltip(r, r["type"]),
                     arrows="to", color="#8a8a8a", font={"size": 10, "align": "middle"})
    net.set_options(json.dumps({
        "physics": {"enabled": physics, "solver": "forceAtlas2Based",
                    "forceAtlas2Based": {"gravitationalConstant": -60, "springLength": 110},
                    "stabilization": {"iterations": 200}},
        "interaction": {"hover": True, "navigationButtons": True, "tooltipDelay": 120},
        "nodes": {"shape": "dot", "font": {"size": 13}},
    }))
    return net.generate_html(notebook=False)


def legend_html(graph):
    """Pequena legenda com as cores dos labels presentes no subgrafo."""
    labels = sorted({main_label(n["labels"]) for n in graph["nodes"]})
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;margin:0 12px 4px 0;font-size:13px">'
        f'<span style="width:11px;height:11px;border-radius:50%;background:{COLORS.get(lb, "#999")};'
        f'display:inline-block;margin-right:5px"></span>{html.escape(lb)}</span>' for lb in labels)
    return f"<div>{chips}</div>"
