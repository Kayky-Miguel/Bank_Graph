import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    CharacterTextSplitter,
)

st.set_page_config(page_title="Lab 1 — Chunking & Embeddings", layout="wide")
st.title("🧪 Lab 1 — Chunking, Embeddings e Espaço Semântico")
st.markdown("Aplique diferentes estratégias de **chunking**, gere **embeddings** e explore o **espaço vetorial**.")

# ---------- SIDEBAR ----------
st.sidebar.header("⚙️ Parâmetros")
modelo_nome = st.sidebar.selectbox(
    "Modelo de Embedding",
    ["sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-pt-v1.5"]
)
chunk_size = st.sidebar.slider("Chunk Size (caracteres)", 100, 1500, 500, 50)
chunk_overlap = st.sidebar.slider("Overlap (caracteres)", 0, 300, 50, 10)
estrategia = st.sidebar.selectbox(
    "Estratégia de Chunking",
    ["RecursiveCharacter", "Fixed-Size (Character)"]
)
reducao = st.sidebar.selectbox("Redução 2D", ["PCA", "t-SNE"])

# ---------- ENTRADA DE TEXTO ----------
st.subheader("📝 Texto de Entrada")
texto_padrao = """
Representação vetorial é a forma como transformamos textos em números.
Bag-of-Words conta a frequência das palavras, mas ignora a ordem e o contexto.
TF-IDF pondera termos raros com maior importância.
Embeddings são representações densas que capturam significado semântico.
Chunking divide documentos grandes em unidades menores e recuperáveis.
O overlap preserva o contexto entre chunks consecutivos.
PCA e t-SNE permitem visualizar embeddings de alta dimensão em 2D.
RAG combina recuperação vetorial com geração por LLMs.
A qualidade do RAG depende fortemente da qualidade do chunking.
Garbage in, garbage out: dados mal preparados geram respostas ruins.
"""
texto = st.text_area("Cole ou edite o texto:", value=texto_padrao, height=250)

# ---------- PROCESSAMENTO ----------
if st.button("🚀 Processar"):
    if not texto.strip():
        st.warning("Insira um texto para processar.")
    else:
        with st.spinner("Carregando modelo..."):
            model = SentenceTransformer(modelo_nome)

        # 1) Chunking
        if estrategia == "RecursiveCharacter":
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""]
            )
        else:
            splitter = CharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=" "
            )
        chunks = splitter.split_text(texto)

        st.success(f"✅ {len(chunks)} chunks gerados com a estratégia **{estrategia}**.")

        # 2) Exibir chunks
        st.subheader("📚 Chunks Gerados")
        for i, c in enumerate(chunks):
            with st.expander(f"Chunk {i+1} ({len(c)} caracteres)"):
                st.write(c)

        # 3) Embeddings
        with st.spinner("Gerando embeddings..."):
            embeddings = model.encode(chunks)

        st.subheader("🔢 Dimensões dos Embeddings")
        st.write(f"Formato: **{embeddings.shape}**")

        # 4) Matriz de similaridade
        st.subheader("📊 Matriz de Similaridade de Cosseno")
        sim = cosine_similarity(embeddings)
        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(sim, cmap="Blues", vmin=0, vmax=1)
        ax.set_xticks(range(len(chunks)))
        ax.set_yticks(range(len(chunks)))
        ax.set_xticklabels([f"C{i+1}" for i in range(len(chunks))])
        ax.set_yticklabels([f"C{i+1}" for i in range(len(chunks))])
        for i in range(len(chunks)):
            for j in range(len(chunks)):
                ax.text(j, i, f"{sim[i,j]:.2f}", ha="center", va="center",
                        color="black" if sim[i,j] < 0.6 else "white", fontsize=8)
        plt.colorbar(im, ax=ax)
        st.pyplot(fig)

        # 5) Visualização 2D
        st.subheader(f"🌐 Espaço Semântico em 2D — {reducao}")
        if reducao == "PCA":
            reducer = PCA(n_components=2)
            coords = reducer.fit_transform(embeddings)
        else:
            perplexity = min(5, len(chunks) - 1) if len(chunks) > 1 else 1
            reducer = TSNE(n_components=2, perplexity=perplexity, random_state=42)
            coords = reducer.fit_transform(embeddings)

        fig2, ax2 = plt.subplots(figsize=(8, 6))
        ax2.scatter(coords[:, 0], coords[:, 1], c=range(len(chunks)), cmap="viridis", s=120)
        for i, (x, y) in enumerate(coords):
            ax2.annotate(f"C{i+1}", (x, y), textcoords="offset points", xytext=(5, 5), fontsize=10)
        ax2.set_xlabel("Componente 1")
        ax2.set_ylabel("Componente 2")
        ax2.set_title(f"Visualização dos Chunks com {reducao}")
        st.pyplot(fig2)

        # 6) Busca semântica simples
        st.subheader("🔍 Busca Semântica")
        query = st.text_input("Faça uma pergunta sobre o texto:")
        if query:
            q_emb = model.encode([query])
            sims = cosine_similarity(q_emb, embeddings)[0]
            ranking = np.argsort(sims)[::-1]
            st.write("**Ranking dos chunks mais similares:**")
            for rank, idx in enumerate(ranking[:3], 1):
                st.markdown(f"**{rank}º Chunk {idx+1}** (score: `{sims[idx]:.3f}`)")
                st.info(chunks[idx])