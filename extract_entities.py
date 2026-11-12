"""Etapa 4 / Passos 2-5 - Text-to-Graph (NER/RE) dos documentos com LLM.

Fluxo: documents.csv -> prompt -> LLM (JSON) -> validacao -> resolucao de entidades -> Neo4j.

Uso:
  pip install anthropic            # (ou openai)
  $env:ANTHROPIC_API_KEY="..."     # nunca escreva a chave no codigo
  python extract_entities.py --data ./BankGraph_AI_Dataset --provider mock --dry-run   # teste sem chave/sem Neo4j
  python extract_entities.py --data ./BankGraph_AI_Dataset --provider anthropic --dry-run  # chama o LLM, nao grava
  python extract_entities.py --data ./BankGraph_AI_Dataset --provider anthropic            # grava no grafo
Provedores: anthropic | openai (OPENAI_API_KEY; para Ollama/Groq/Gemini defina OPENAI_BASE_URL) | mock.
O modelo vem de LLM_MODEL (ou --model). As respostas ficam em extraction_cache.json: reexecutar nao gasta API.
Saida para avaliacao: extraction_results.json
"""
import argparse, hashlib, json, os, re, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# ---------------- 1. Esquema permitido (a decisao mais importante) ----------------
ENTITY_TYPES = {
    "RuleTopic":  "tema da regra (use exatamente o tema informado)",
    "Segment":    "segmento de cliente (ex.: BASIC)",
    "Limit":      "limite de valor (ex.: R$ 2.000 por dia)",
    "Term":       "prazo ou quantidade (ex.: 6 a 60 parcelas)",
    "Condition":  "condicao, requisito ou situacao gatilho",
    "Action":     "acao tomada (ex.: alerta, analise manual, revisao, bloqueio)",
    "Obligation": "obrigacao de registro ou procedimento",
}
# relacao -> pares (tipo_origem, tipo_destino) permitidos
RELATIONS = {
    "APPLIES_TO":  {("RuleTopic", "Segment")},
    "HAS_LIMIT":   {("RuleTopic", "Limit")},
    "HAS_TERM":    {("RuleTopic", "Term")},
    "REQUIRES":    {("RuleTopic", "Condition")},
    "MAY_TRIGGER": {("RuleTopic", "Action"), ("Condition", "Action")},
    "MUST_RECORD": {("RuleTopic", "Obligation")},
}

SYSTEM = "Voce extrai entidades e relacoes de regras bancarias ficticias em portugues. Responda SOMENTE com JSON valido."

def build_prompt(topic, text):
    ents = "\n".join(f"- {t}: {d}" for t, d in ENTITY_TYPES.items())
    rels = "\n".join(f"- {r}: " + ", ".join(f"{a}->{b}" for a, b in sorted(p)) for r, p in RELATIONS.items())
    return f"""Extraia entidades e relacoes do texto abaixo.

REGRAS:
- Extraia SOMENTE o que esta escrito no texto. Nao invente nada.
- Use apenas estes tipos de entidade:
{ents}
- Use apenas estas relacoes (origem->destino):
{rels}
- A entidade RuleTopic deve ter exatamente o nome do tema informado.
- Nomes curtos e canonicos (ex.: "R$ 2.000 por dia", "validacao cadastral").
- Se nao houver nada para um tipo, nao o inclua.

Formato da resposta:
{{"entidades":[{{"nome":"...","tipo":"..."}}],"relacoes":[{{"origem":"...","tipo":"...","destino":"..."}}]}}

Exemplo
Tema: Saque Noturno
Texto: Saques acima de R$ 500 no periodo noturno podem exigir confirmacao adicional.
Resposta: {{"entidades":[{{"nome":"Saque Noturno","tipo":"RuleTopic"}},{{"nome":"saques acima de R$ 500 no periodo noturno","tipo":"Condition"}},{{"nome":"confirmacao adicional","tipo":"Action"}}],"relacoes":[{{"origem":"Saque Noturno","tipo":"REQUIRES","destino":"saques acima de R$ 500 no periodo noturno"}},{{"origem":"saques acima de R$ 500 no periodo noturno","tipo":"MAY_TRIGGER","destino":"confirmacao adicional"}}]}}

Agora o seu caso
Tema: {topic}
Texto: {text}
Resposta:"""

# ---------------- 2. Utilitarios ----------------
def normalize(s):
    """minusculas, sem acento, sem pontuacao, espacos colapsados (chave para resolver duplicatas)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()

def clean_topic(title):
    return re.sub(r"\s*-\s*Documento\s*\d+\s*$", "", title).strip()

def clean_text(text):
    return re.sub(r"\s*Documento fict[ií]cio.*$", "", text).strip()

def key_of(etype, name):
    return f"{etype}:{normalize(name)}"

def parse_json(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", raw, flags=re.S)
    return json.loads(m.group(0) if m else raw)

def grounded(name, text_norm):
    """Anti-alucinacao: pelo menos metade dos termos relevantes da entidade aparece no texto."""
    toks = [t for t in normalize(name).split() if len(t) >= 4 or t.isdigit()]
    if not toks:
        return True
    return sum(t in text_norm.split() or t in text_norm for t in toks) / len(toks) >= 0.5

# ---------------- 3. Validacao da resposta do LLM ----------------
def validate(data, topic, text):
    """Retorna (entidades, relacoes, descartados). So passa o que respeita o esquema e esta no texto."""
    text_norm, dropped, ents = normalize(text), [], {}
    ents[key_of("RuleTopic", topic)] = {"name": topic, "type": "RuleTopic"}
    for e in data.get("entidades", []) if isinstance(data, dict) else []:
        name, etype = str(e.get("nome", "")).strip(), e.get("tipo")
        if etype not in ENTITY_TYPES or not name or len(name) > 120:
            dropped.append({"item": e, "motivo": "tipo/nome invalido"}); continue
        if etype == "RuleTopic":
            continue                                   # o tema vem do titulo, nao do LLM
        if not grounded(name, text_norm):
            dropped.append({"item": e, "motivo": "nao esta no texto"}); continue
        ents.setdefault(key_of(etype, name), {"name": name, "type": etype})
    rels = {}
    for r in data.get("relacoes", []) if isinstance(data, dict) else []:
        rtype = r.get("tipo")
        src = key_of("RuleTopic", topic) if normalize(r.get("origem", "")) == normalize(topic) else None
        if src is None:
            src = next((k for k, v in ents.items() if normalize(v["name"]) == normalize(r.get("origem", ""))), None)
        dst = next((k for k, v in ents.items() if normalize(v["name"]) == normalize(r.get("destino", ""))), None)
        if rtype not in RELATIONS or not src or not dst or src not in ents:
            dropped.append({"item": r, "motivo": "relacao invalida ou entidade inexistente"}); continue
        if (ents[src]["type"], ents[dst]["type"]) not in RELATIONS[rtype]:
            dropped.append({"item": r, "motivo": "tipos incompativeis com a relacao"}); continue
        rels[(src, rtype, dst)] = {"source": src, "type": rtype, "target": dst}
    return list(ents.items()), list(rels.values()), dropped

# ---------------- 4. Chamada ao LLM (com cache) ----------------
def call_llm(provider, model, prompt):
    if provider == "mock":
        topic = re.search(r"Tema: (.*)\nTexto: (.*)\nResposta:$", prompt.split("Agora o seu caso")[1], flags=re.S)
        t, txt = topic.group(1), topic.group(2)
        ents = [{"nome": t, "tipo": "RuleTopic"}]; rels = []
        if "BASIC" in txt:
            ents.append({"nome": "BASIC", "tipo": "Segment"}); rels.append({"origem": t, "tipo": "APPLIES_TO", "destino": "BASIC"})
        m = re.search(r"R\$ ?[\d.]+", txt)
        if m:
            ents.append({"nome": m.group(0) + " por dia", "tipo": "Limit"}); rels.append({"origem": t, "tipo": "HAS_LIMIT", "destino": m.group(0) + " por dia"})
        return json.dumps({"entidades": ents, "relacoes": rels}, ensure_ascii=False)
    if provider == "anthropic":
        import anthropic
        r = anthropic.Anthropic().messages.create(model=model, max_tokens=1200, temperature=0, system=SYSTEM,
                                                  messages=[{"role": "user", "content": prompt}])
        return r.content[0].text
    if provider == "openai":
        from openai import OpenAI
        r = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "ollama")).chat.completions.create(
            model=model, temperature=0, messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
        return r.choices[0].message.content
    raise SystemExit(f"provedor desconhecido: {provider}")

def extract(provider, model, topic, text, cache, retries=2):
    prompt = build_prompt(topic, text)
    ck = hashlib.sha1(f"{provider}|{model}|{prompt}".encode()).hexdigest()
    for attempt in range(retries + 1):
        raw = cache.get(ck) or call_llm(provider, model, prompt)
        try:
            data = parse_json(raw)
            cache[ck] = raw
            return data
        except json.JSONDecodeError:
            cache.pop(ck, None)
    return {"entidades": [], "relacoes": [], "erro": "JSON invalido do LLM"}

# ---------------- 5. Resolucao de entidades ----------------
def semantic_merge(entities, embed_fn, threshold):
    """Junta nomes parecidos DO MESMO TIPO por similaridade de embedding. Retorna {chave: chave_canonica}.
    embed_fn(lista_de_textos) -> matriz normalizada (n x d). Revise os merges impressos: o limiar e empirico."""
    import numpy as np
    alias = {}
    by_type = defaultdict(list)
    for k, v in entities.items():
        by_type[v["type"]].append(k)
    for etype, keys in by_type.items():
        if etype == "RuleTopic" or len(keys) < 2:
            continue
        vecs = np.asarray(embed_fn([entities[k]["name"] for k in keys]))
        sim = vecs @ vecs.T
        parent = list(range(len(keys)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]; i = parent[i]
            return i
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                if sim[i, j] >= threshold:
                    parent[find(j)] = find(i)
        groups = defaultdict(list)
        for i, k in enumerate(keys):
            groups[find(i)].append(k)
        for g in groups.values():
            if len(g) > 1:
                canon = min(g, key=lambda k: len(entities[k]["name"]))
                for k in g:
                    if k != canon:
                        alias[k] = canon
    return alias

# ---------------- 6. Gravacao no Neo4j ----------------
def write_graph(results, entities, relations):
    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with drv.session() as s:
        s.run("CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE")
        for k, v in entities.items():
            # v['type'] vem da allowlist ENTITY_TYPES, entao interpolar no label e seguro
            s.run(f"MERGE (e:Entity {{key:$k}}) ON CREATE SET e.name=$n, e.type=$t SET e:{v['type']}", k=k, n=v["name"], t=v["type"])
        for (src, rtype, dst), docs in relations.items():
            s.run(f"""MATCH (a:Entity {{key:$a}}), (b:Entity {{key:$b}})
                      MERGE (a)-[r:{rtype}]->(b) SET r.doc_ids = $docs""", a=src, b=dst, docs=sorted(docs))
        for doc_id, ekeys in results.items():
            for k in ekeys:
                s.run("MATCH (d:Document {document_id:$d}), (e:Entity {key:$k}) MERGE (d)-[:MENTIONS]->(e)", d=doc_id, k=k)
        # liga cada BankingRule do CSV ao tema canonico (30 regras -> 10 temas)
        s.run("""MATCH (r:BankingRule)
                 WITH r, r.rule_name AS n MATCH (t:RuleTopic:Entity) WHERE t.name = n
                 MERGE (r)-[:INSTANCE_OF]->(t)""")
    drv.close()

def load_results(path):
    """Reconstroi a extracao validada a partir de extraction_results.json (sem LLM, sem chave de API).
    Mesmo formato que o laco de extracao produz: {doc: {topic, entities:[(key, v)], relations:[{source,type,target}]}}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    per_doc = {}
    for doc_id, r in data.items():
        ents = [(key_of(e["type"], e["name"]), {"name": e["name"], "type": e["type"]}) for e in r["entities"]]
        by_name = {normalize(v["name"]): k for k, v in ents}
        rels = []
        for x in r["relations"]:
            src, dst = by_name.get(normalize(x["source"])), by_name.get(normalize(x["target"]))
            if src and dst:
                rels.append({"source": src, "type": x["type"], "target": dst})
        per_doc[doc_id] = {"topic": r["topic"], "entities": ents, "relations": rels, "dropped": r.get("dropped", [])}
    return per_doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "mock"])
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", "claude-haiku-5-5"))
    ap.add_argument("--limit", type=int, help="processa so os N primeiros documentos (teste)")
    ap.add_argument("--semantic-merge", type=float, metavar="LIMIAR", help="ex.: 0.9 (usa sentence-transformers)")
    ap.add_argument("--dry-run", action="store_true", help="nao grava no Neo4j")
    ap.add_argument("--from-results", metavar="JSON", nargs="?", const="extraction_results.json",
                    help="grava no Neo4j a extracao ja validada (extraction_results.json), sem chamar o LLM")
    a = ap.parse_args()

    import pandas as pd
    docs = pd.read_csv(Path(a.data) / "documents.csv", encoding="utf-8-sig", dtype=str)
    if a.limit:
        docs = docs.head(a.limit)
    cache_path = Path("extraction_cache.json")
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    per_doc, all_ents, dropped_total = {}, {}, 0
    if a.from_results:
        per_doc = load_results(a.from_results)
        if a.limit:
            per_doc = dict(list(per_doc.items())[:a.limit])
        for doc_id, r in per_doc.items():
            dropped_total += len(r["dropped"])
            for k, v in r["entities"]:
                all_ents.setdefault(k, v)
        print(f"{len(per_doc)} documentos lidos de {a.from_results} (sem chamar o LLM)")
    for _, d in ([] if a.from_results else docs.iterrows()):
        topic, text = clean_topic(d["title"]), clean_text(d["text"])
        data = extract(a.provider, a.model, topic, text, cache)
        ents, rels, dropped = validate(data, topic, text)
        dropped_total += len(dropped)
        per_doc[d["document_id"]] = {"topic": topic, "text": text, "entities": ents, "relations": rels, "dropped": dropped}
        for k, v in ents:
            all_ents.setdefault(k, v)
        print(f"{d['document_id']}: {len(ents)} entidades, {len(rels)} relacoes, {len(dropped)} descartados")
    if not a.from_results:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    n_before = len(all_ents)
    alias = {}
    if a.semantic_merge:
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(os.environ.get("EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"))
        alias = semantic_merge(all_ents, lambda xs: m.encode(xs, normalize_embeddings=True), a.semantic_merge)
        for k, c in alias.items():
            print(f"  merge: '{all_ents[k]['name']}' -> '{all_ents[c]['name']}'")
    canon = lambda k: alias.get(k, k)

    entities = {k: v for k, v in all_ents.items() if k not in alias}
    relations = defaultdict(set)
    mentions = defaultdict(set)
    for doc_id, r in per_doc.items():
        for k, _ in r["entities"]:
            mentions[doc_id].add(canon(k))
        for rel in r["relations"]:
            relations[(canon(rel["source"]), rel["type"], canon(rel["target"]))].add(doc_id)
    print(f"\nEntidades: {n_before} unicas por nome normalizado -> {len(entities)} apos resolucao semantica")
    print("Por tipo:", dict(Counter(v["type"] for v in entities.values())))
    print(f"Relacoes distintas: {len(relations)} | itens descartados na validacao: {dropped_total}")

    if not a.from_results:   # no modo --from-results o arquivo e a entrada: nao reescrever
      Path("extraction_results.json").write_text(json.dumps(
        {d: {"topic": r["topic"], "entities": [v for _, v in r["entities"]],
             "relations": [{"source": all_ents[x["source"]]["name"], "type": x["type"], "target": all_ents[x["target"]]["name"]} for x in r["relations"]],
             "dropped": r["dropped"]} for d, r in per_doc.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.dry_run:
        print("dry-run: nada foi gravado no Neo4j (resultado em extraction_results.json)"); return
    write_graph(mentions, entities, relations)
    print("Gravado no Neo4j.")

if __name__ == "__main__":
    main()