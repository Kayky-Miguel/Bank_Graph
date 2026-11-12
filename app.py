"""BankGraph AI - Etapa 6: interface Streamlit.

Uso (mesmas variaveis NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD dos outros scripts):
  python -m streamlit run app.py

A recuperacao vem da Etapa 5 (retrieval.py, funcao answer). Enquanto ela nao existir,
a interface usa o baseline de ui_backend.py. Veja o contrato no topo de ui_backend.py.
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from graph_view import caption, legend_html, main_label, render_html
from ui_backend import DEFAULT_REF_DATE, DISCLAIMER, BaselineRetriever, call_backend, load_external

st.set_page_config(page_title="BankGraph AI", page_icon="🕸️", layout="wide")

DATA = Path(__file__).parent / "BankGraph_AI_Dataset"
DEMO_QUESTIONS = [
    "Quais clientes possuem relacionamento com contas que realizaram transações sinalizadas nos últimos 30 dias "
    "e, entre eles, quais possuem empréstimos ativos?",
    "Quais contas pertencem ao cliente C0208?",
    "Quais clientes têm conta conjunta e empréstimo ativo?",
    "Quais clientes têm relação indireta, por conta conjunta, com contas que tiveram transações sinalizadas nos últimos 365 dias?",
    "Quais estabelecimentos concentram pagamentos de vários clientes?",
    "Quais regras orientam a revisão de transferências recorrentes?",
    "Qual é o limite do PIX para o segmento BASIC?",
    "Um alerta permite afirmar que houve fraude?",
    "Qual a previsão do tempo para amanhã?",
]


@st.cache_data
def evaluation_questions():
    try:
        df = pd.read_csv(DATA / "evaluation_cases.csv", encoding="utf-8-sig")
        return [f"{r.case_id}: {r.question}" for r in df.itertuples()]
    except Exception:
        return []


@st.cache_resource
def baseline():
    return BaselineRetriever()


@st.cache_data(ttl=60, show_spinner=False)
def graph_status():
    return baseline().health()


def backends():
    """{nome: funcao}; a Etapa 5 aparece primeiro quando existe."""
    out, info = {}, None
    try:
        name, fn = load_external()
        if fn is None or isinstance(fn, str):
            info = fn if isinstance(fn, str) else None
        else:
            out[f"Etapa 5 ({name})"] = fn
    except Exception as e:          # o modulo existe mas quebrou ao importar
        info = f"retrieval.py falhou ao importar: {e}"
    out[BaselineRetriever.name] = lambda q, **kw: baseline().answer(q, **kw)
    return out, info


# ------------------------------------------------------------------ estado
if "history" not in st.session_state:
    st.session_state.history = []          # lista de resultados (mais recente por ultimo)
if "selected" not in st.session_state:
    st.session_state.selected = None
if "question" not in st.session_state:
    st.session_state.question = ""

# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.header("Configuração")
    options, info = backends()
    backend_name = st.selectbox("Mecanismo de recuperação", list(options))
    if info:
        st.caption(f"Etapa 5 indisponível: {info}. Usando o baseline.")
    try:
        ok, problems, counts = graph_status()
        if ok:
            st.caption(f"Neo4j: {counts['customers']} clientes, {counts['documents']} documentos, "
                       f"{counts['entities']} entidades extraídas.")
        else:
            st.error("Grafo incompleto:\n\n" + "\n\n".join(f"- {p}" for p in problems))
    except KeyError:
        st.warning("Defina NEO4J_URI, NEO4J_USER e NEO4J_PASSWORD antes de abrir o app.")
    except Exception as e:
        st.warning(f"Sem conexão com o Neo4j ({type(e).__name__}). A instância está ligada?")
    ref_date = st.text_input("Data de referência", DEFAULT_REF_DATE,
                             help="Os dados terminam em 2026-11-10; janelas como 'últimos 30 dias' contam a partir daqui.")
    limit = st.slider("Máximo de linhas por consulta", 5, 100, 25, 5)
    physics = st.toggle("Animação do grafo (física)", True)

    st.divider()
    st.subheader("Histórico")
    if not st.session_state.history:
        st.caption("Nenhuma pergunta ainda.")
    for i in range(len(st.session_state.history) - 1, -1, -1):
        h = st.session_state.history[i]
        label = h["question"] if len(h["question"]) <= 60 else h["question"][:58] + "…"
        if st.button(label, key=f"hist{i}", width="stretch"):
            st.session_state.selected = i
    if st.session_state.history and st.button("Limpar histórico"):
        st.session_state.history, st.session_state.selected = [], None
        st.rerun()

# ------------------------------------------------------------------ cabecalho e pergunta
st.title("BankGraph AI")
st.caption("Perguntas em linguagem natural sobre clientes, contas, transações e regras bancárias, "
           "respondidas com evidências do grafo Neo4j (GraphRAG + KAG).")
st.info(DISCLAIMER, icon="ℹ️")


def _pick(key):
    value = st.session_state[key]
    if value:
        st.session_state.question = value.split(": ", 1)[1] if key == "pick_eval" else value


c1, c2 = st.columns(2)
c1.selectbox("Perguntas de demonstração", [""] + DEMO_QUESTIONS, key="pick_demo", on_change=_pick, args=("pick_demo",))
c2.selectbox("Casos de avaliação (evaluation_cases.csv)", [""] + evaluation_questions(), key="pick_eval",
             on_change=_pick, args=("pick_eval",))

with st.form("ask"):
    question = st.text_area("Pergunta", key="question", height=80,
                            placeholder="Ex.: Quais empréstimos do cliente C0208 estão ativos?")
    submitted = st.form_submit_button("Perguntar", type="primary")

if submitted:
    if not question.strip():
        st.warning("Escreva uma pergunta.")
    else:
        with st.spinner("Recuperando evidências no grafo…"):
            try:
                res = call_backend(options[backend_name], question.strip(), ref_date=ref_date, limit=limit)
                res["backend"] = backend_name
            except KeyError as e:
                st.error(f"Variável de ambiente ausente: {e}. Defina NEO4J_URI, NEO4J_USER e NEO4J_PASSWORD "
                         "na mesma janela em que roda o Streamlit.")
                st.stop()
            except Exception as e:
                st.error(f"Falha na recuperação ({type(e).__name__}): {e}")
                st.stop()
        st.session_state.history.append(res)
        st.session_state.selected = len(st.session_state.history) - 1

if st.session_state.selected is None:
    st.stop()

res = st.session_state.history[st.session_state.selected]
graph = res["graph"]

# ------------------------------------------------------------------ resposta
st.divider()
st.markdown(f"**Pergunta:** {res['question']}")

conf = res.get("confidence")
conf_txt = f"{conf:.0%}" if isinstance(conf, (int, float)) else (conf or "não informado")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Confiança", conf_txt, help="Grau de sustentação da resposta pelas evidências recuperadas. "
                                       "Não é probabilidade de fraude. " + (res.get("confidence_reason") or ""))
m2.metric("Nós no subgrafo", len(graph["nodes"]))
m3.metric("Fontes documentais", len(res["sources"]))
m4.metric("Latência", f"{res.get('latency_ms', 0):,.0f} ms")

with st.container(border=True):
    st.markdown("##### Resposta gerada")
    if res["insufficient_evidence"]:
        st.warning(res["answer"], icon="⚠️")
    else:
        st.markdown(res["answer"])
    st.caption(f"Mecanismo: {res.get('backend', '?')}"
               + (f" · Confiança: {res['confidence_reason']}" if res.get("confidence_reason") else ""))
for n in res["notes"]:
    st.caption(f"• {n}")

if res["entity_ids"]:
    st.markdown("**Entidades citadas:** " + " ".join(f"`{e}`" for e in dict.fromkeys(res["entity_ids"])))

# ------------------------------------------------------------------ evidencias
t_graph, t_facts, t_src, t_cypher, t_raw = st.tabs(
    ["Subgrafo", "Fatos recuperados", f"Fontes ({len(res['sources'])})", f"Cypher ({len(res['queries'])})", "JSON"])

with t_graph:
    if not graph["nodes"]:
        st.caption("Esta resposta não trouxe nós do grafo.")
    else:
        if len(graph["nodes"]) > 300:
            st.warning(f"Subgrafo grande ({len(graph['nodes'])} nós); reduza o limite na barra lateral.")
        st.markdown(legend_html(graph), unsafe_allow_html=True)
        components.html(render_html(graph, highlight=res["entity_ids"], physics=physics), height=580, scrolling=False)
        st.caption("Arraste para mover, use a roda do mouse para zoom e passe o mouse sobre nós e arestas para ver as "
                   "propriedades. Nós com borda escura são entidades citadas na resposta.")

        st.markdown("##### Detalhes")
        by_id = {n["id"]: n for n in graph["nodes"]}
        labels = sorted({main_label(n["labels"]) for n in graph["nodes"]})
        cl, cn = st.columns([1, 2])
        lb = cl.selectbox("Tipo de nó", labels)
        nodes = sorted((n for n in graph["nodes"] if main_label(n["labels"]) == lb), key=caption)
        node = cn.selectbox("Nó", nodes, format_func=caption)
        if node:
            d1, d2 = st.columns(2)
            with d1:
                st.markdown(f"**{':'.join(node['labels'])} · {caption(node)}**")
                st.json(node["props"], expanded=True)
            with d2:
                rels = [r for r in graph["relationships"] if node["id"] in (r["start"], r["end"])]
                st.markdown(f"**Relacionamentos no subgrafo ({len(rels)})**")
                for r in rels:
                    out = r["start"] == node["id"]
                    other = by_id.get(r["end"] if out else r["start"])
                    arrow = f"-[:{r['type']}]->" if out else f"<-[:{r['type']}]-"
                    title = f"{caption(node)} {arrow} {caption(other) if other else '?'}"
                    with st.expander(title):
                        if r["props"]:
                            st.json(r["props"])
                        if other:
                            st.json(other["props"], expanded=False)

        with st.expander("Todos os relacionamentos (tabela)"):
            st.dataframe(pd.DataFrame([{"origem": caption(by_id[r["start"]]), "relação": r["type"],
                                        "destino": caption(by_id[r["end"]]),
                                        "propriedades": json.dumps(r["props"], ensure_ascii=False) if r["props"] else ""}
                                       for r in graph["relationships"]]), width="stretch", hide_index=True)

with t_facts:
    if res["rows"]:
        st.dataframe(pd.DataFrame(res["rows"]), width="stretch", hide_index=True)
    else:
        st.caption("Sem tabela de fatos para esta resposta.")

with t_src:
    if not res["sources"]:
        st.caption("Nenhum documento foi usado nesta resposta.")
    for s in res["sources"]:
        score = f" · similaridade {s['score']:.2f}" if isinstance(s.get("score"), (int, float)) else ""
        head = f"{s.get('document_id', '?')} · {s.get('title', '')}"
        meta = ", ".join(x for x in [f"versão {s['version']}" if s.get("version") else "",
                                    f"seção {s['section']}" if s.get("section") else "",
                                    f"p. {s['page']}" if s.get("page") else ""] if x)
        with st.expander(head + score):
            if meta:
                st.caption(meta)
            st.write(s.get("text", ""))

with t_cypher:
    if not res["queries"]:
        st.caption("Nenhuma consulta Cypher informada.")
    for i, q in enumerate(res["queries"], 1):
        st.markdown(f"**Consulta {i}**" + (f": {q['purpose']}" if q.get("purpose") else "")
                    + (f" · {q['rows']} linha(s)" if q.get("rows") is not None else ""))
        st.code(q["cypher"], language="cypher")
        if q["params"]:
            st.markdown("Parâmetros")
            st.json(q["params"])

with t_raw:
    st.download_button("Baixar resultado (JSON)", json.dumps(res, ensure_ascii=False, indent=1, default=str),
                       file_name="bankgraph_resposta.json", mime="application/json")
    st.json({k: v for k, v in res.items() if k != "graph"}, expanded=False)
