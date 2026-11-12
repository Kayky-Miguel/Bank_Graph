# BankGraph AI

Assistente para análise de relacionamentos e conhecimento bancário com **GraphRAG** e **KAG**, sobre um grafo no **Neo4j**.

> **Projeto acadêmico com dados 100% sintéticos.** Alertas e transações sinalizadas (`flagged = true`) são sinais simulados e **não comprovam fraude**. O sistema não executa operações bancárias nem toma decisões financeiras.

## Estado do projeto

| Etapa | Descrição | Situação |
|---|---|---|
| 1 | Definição do problema e requisitos | Concluída |
| 2 | Dados sintéticos e documentos | Concluída |
| 3 | Modelagem LPG no Neo4j (schema + ingestão) | Concluída |
| 4 | Pipeline Text-to-Graph (NER/RE) | Concluída |
| 5 | Recuperação híbrida GraphRAG/KAG | Concluída |
| 6 | Interface Streamlit e visualização do subgrafo | A fazer |
| 7 | Avaliação e testes | A fazer |
| 8 | Documentação, artigo e apresentação | A fazer |

## Estrutura do repositório

```
BankGraph_AI_Dataset/     CSVs sintéticos (clientes, contas, transações, documentos...) e README do dataset
schema.cypher             constraints e índices (B-tree, full-text, vetorial)
ingest.py                 cria o schema, carrega os CSVs e valida as contagens
queries.cypher            consultas de validação e de demonstração (multi-hop incluído)
embed_docs.py             gera embeddings de Document e BankingRule e grava no Neo4j
extract_entities.py       extração de entidades/relações dos documentos com LLM + resolução de entidades
evaluate_extraction.py    precisão, recall e F1 da extração contra o gabarito
gold_annotations.json     gabarito anotado à mão (DOC001–DOC010, um por tema)
extraction_cache.json     respostas do LLM em cache (permite reproduzir sem chave de API)
extraction_results.json   saída validada da extração
requirements.txt          dependências Python
```

## Modelo do grafo

```
(Customer)-[:OWNS {ownership_type}]->(Account)-[:SENT]->(Transaction)-[:PAID_TO]->(Merchant)
(Alert)-[:RAISED_ON]->(Transaction)
(Customer)-[:HAS_LOAN]->(Loan)-[:ON_ACCOUNT]->(Account)
(Customer)-[:HAS_CARD]->(Card)-[:LINKED_TO]->(Account)
(Account)-[:BELONGS_TO]->(Branch)<-[:WORKS_AT]-(Employee)
(Customer)-[:FILED]->(Complaint)
(Document)-[:DESCRIBES]->(BankingRule)    (Loan)-[:FOLLOWS]->(BankingRule)

Extraídos dos documentos (Etapa 4):
(Document)-[:MENTIONS]->(Entity)          Entity: RuleTopic | Segment | Limit | Term | Condition | Action | Obligation
(RuleTopic)-[:APPLIES_TO|HAS_LIMIT|HAS_TERM|REQUIRES|MAY_TRIGGER|MUST_RECORD]->(Entity)
(BankingRule)-[:INSTANCE_OF]->(RuleTopic)   30 regras do CSV → 10 temas canônicos
```

Observações de modelagem:
- As transações do dataset **não têm conta de destino**, só estabelecimento. Por isso o modelo usa `Account -[:SENT]-> Transaction -[:PAID_TO]-> Merchant`.
- `Loan -[:FOLLOWS]-> BankingRule` liga todo empréstimo às regras de nome "Empréstimo Pessoal" (heurística de projeto).
- A ligação indireta entre clientes acontece via **conta conjunta** (`ownership_type = JOINT`).

## Requisitos

- **Python** 3.9 ou mais novo
- **Neo4j** 5.x ou mais novo, com suporte a índice vetorial (testado na versão 2026.10 pelo Neo4j Desktop)
- **Git**
- Chave de API de LLM **apenas** se for refazer a extração do zero (veja abaixo)

## Instalação

```bash
git clone https://github.com/Kayky-Miguel/Bank_Graph.git
cd Bank_Graph
python -m venv .venv
```
Ative o ambiente virtual:
- Windows (PowerShell): `.venv\Scripts\activate`
- Mac/Linux: `source .venv/bin/activate`

```bash
python -m pip install -r requirements.txt
```

## Configuração

Cada pessoa usa **a sua própria instância** do Neo4j. O grafo não vai no repositório: ele é recriado rodando os scripts abaixo. Nenhuma senha ou chave fica no código; tudo vem de variáveis de ambiente.

1. No Neo4j Desktop, crie uma instância, defina uma senha, inicie-a (status *Running*) e confirme que existe um database chamado `neo4j`.
2. Defina as variáveis **na mesma janela de terminal** em que for rodar os scripts:

Windows (PowerShell):
```powershell
$env:NEO4J_URI="neo4j://127.0.0.1:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="senha-da-sua-instancia"
```
Mac/Linux:
```bash
export NEO4J_URI="neo4j://127.0.0.1:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="senha-da-sua-instancia"
```
As variáveis valem só para a janela em que foram definidas. Em outra janela, defina de novo.

## Como rodar (nesta ordem)

**1. Ingestão estruturada.** Cria constraints e índices, carrega os 14 CSVs e compara as contagens do grafo com as dos CSVs. Todas as linhas devem sair com `OK`.
```bash
python ingest.py --data ./BankGraph_AI_Dataset
```
(`--dry-run` só lê os CSVs sem tocar no banco; `--wipe` apaga o grafo antes de carregar.)

**2. Embeddings.** Na primeira execução baixa o modelo multilíngue (cerca de 470 MB, uma vez por máquina).
```bash
python embed_docs.py
python embed_docs.py --query "limite do PIX"     # teste da busca vetorial
```

**3. Extração de entidades e relações (Text-to-Graph).**
```bash
python extract_entities.py --data ./BankGraph_AI_Dataset --provider openai --model gpt-4o-mini
```
O repositório inclui o `extraction_cache.json`. Usando **o mesmo provedor e o mesmo modelo** com que o cache foi gerado, o script lê as respostas guardadas e **não chama a API**, então não é preciso chave. Se mudar o modelo ou o prompt, o cache não vale e será preciso definir `OPENAI_API_KEY`:
```bash
# Windows: $env:OPENAI_API_KEY="..."      Mac/Linux: export OPENAI_API_KEY="..."
```
> **Atenção:** ao rodar do zero, o `extraction_cache.json` pode não bater com o prompt atual (o script então tenta chamar a API e falha com `401` se não houver chave). Alternativa sem chave e sem LLM: `python load_extraction_results.py` grava o `extraction_results.json` (saída já validada) direto no Neo4j; use `--dry-run` para só conferir as contagens (esperado: 30 documentos, 34 entidades, 23 relações).

Use `--dry-run` para extrair sem gravar no Neo4j e `--limit N` para testar em poucos documentos. Para testar o fluxo sem LLM, use `--provider mock`.

**4. Avaliação da extração.**
```bash
python evaluate_extraction.py
```

## Etapa 5: recuperação híbrida (GraphRAG/KAG)

Responde perguntas em linguagem natural combinando busca vetorial, consulta Cypher validada e regras explícitas (KAG), e devolve a resposta com evidências.

Pré-requisitos: etapas 1 a 4 rodadas (ingestão, embeddings e extração gravada no grafo) e `OPENAI_API_KEY` definida (ou `--provider mock` para testar o fluxo sem chave). Opcionais: `LLM_MODEL` (padrão `gpt-4o-mini`) e `OPENAI_BASE_URL` (outros provedores compatíveis).

```bash
python test_etapa5.py            # testes offline (validador de Cypher, abstenção, IDs sem evidência)
python graphrag_pipeline.py "Quais clientes têm transação sinalizada nos últimos 30 dias e empréstimo ativo?"
python graphrag_pipeline.py "Qual a capital da França?"        # deve se abster
```

Fluxo: embedding da pergunta, busca vetorial, o LLM escolhe uma consulta pronta ou propõe um Cypher, validador (só leitura, labels e relações permitidos, profundidade <= 4, LIMIT <= 100), execução em transação de leitura com timeout, regras do documento de origem (KAG) e resposta somente com o contexto recuperado.

Saída (JSON): resposta, `abstained`, `cypher`, `params`, `graph_rows`, `documents`, `rules`, `entity_ids`, `unsupported_ids` (IDs citados sem evidência), `confidence` (heurística, não probabilidade), `errors` e `latency_s`.

Resultado esperado da pergunta central (ref. 2026-11-10): 7 clientes com transação sinalizada; 3 com empréstimo ativo (C0208, C0234, C0410).

Limitações conhecidas: o LLM não é determinístico e pode omitir itens de uma lista; o limiar de similaridade (`MIN_VECTOR_SCORE = 0.60`) foi calibrado com poucas perguntas e trechos pouco relacionados podem aparecer logo acima dele; a função `db.index.vector.queryNodes` está obsoleta no Neo4j novo (continua funcionando; migrar para `SEARCH` é um próximo passo).

## Conferindo o resultado

Na janela *Query* do Neo4j, rode as consultas de `queries.cypher`. Com data de referência fixa em `2026-11-10` (os dados terminam nessa data):

```cypher
:param ref => date('2026-11-10');
```
Valores esperados da pergunta central (clientes com transação sinalizada nos últimos 30 dias): **7 clientes**, dos quais **3 com empréstimo ativo** (C0208, C0234, C0410). A relação indireta por conta conjunta é rara no dataset; use uma janela maior (`:param dias => 365`).

Checagem da extração:
```cypher
MATCH (r:BankingRule)-[:INSTANCE_OF]->(t:RuleTopic) RETURN t.name, count(r) ORDER BY t.name;
```
Deve retornar 10 temas, com 3 regras cada.

## Avaliação da extração (resultado parcial)

Primeira rodada, comparação estrita (nome normalizado igual), 10 documentos anotados:

| | Precisão | Recall | F1 |
|---|---|---|---|
| Entidades (NER) | 0,62 | 0,75 | 0,68 |
| Relações (RE) | 0,43 | 0,56 | 0,49 |

Boa parte da diferença vem de convenção de granularidade (enumerações agrupadas no gabarito e separadas pelo LLM) e de variação de nome, não de alucinação. A análise de erros completa faz parte da Etapa 7. **Limitação:** os 30 documentos são 10 textos repetidos em 3 versões, então os splits `train`/`dev`/`test` não são independentes entre si.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `ModuleNotFoundError: neo4j` | Dependências não instaladas, ou ambiente virtual não ativado. Use `python -m pip install -r requirements.txt`. |
| `AuthError` | Senha do Neo4j errada. |
| Erro de conexão ou roteamento | Instância parada, ou tente trocar `neo4j://` por `bolt://` no URI. |
| `Databases (0)` no Desktop | Crie um database chamado `neo4j`. |
| `schema.cypher` não encontrado | Ele deve ficar na mesma pasta do `ingest.py`. |
| `ERRO` na validação da ingestão | Alguma linha não achou o nó pai e foi descartada; compare as contagens. |
| `cd` falha no PowerShell | O caminho tem espaços: use aspas, `cd "C:\minha pasta"`. |
| Embeddings lentos na 1ª vez | Download do modelo; acontece uma vez por máquina. |

## Segurança

- Não coloque senhas nem chaves de API em arquivos do repositório; use sempre variáveis de ambiente.
- Se uma chave for exposta, revogue-a no painel do provedor e gere outra.
- Todos os dados são fictícios. Não inclua CPF, número de conta, cartão ou qualquer informação real.

## Próximos passos

1. **Etapa 6:** interface Streamlit com a pergunta, a resposta, as evidências, a consulta Cypher executada e o subgrafo.
2. **Etapa 7:** perguntas de teste (respondíveis, não respondíveis e ambíguas), comparação entre busca vetorial isolada e híbrida, e avaliação final nos documentos do split `test`.

Etapa 5 concluída (ver seção acima).

## Dataset

Descrição dos arquivos e dos campos em `BankGraph_AI_Dataset/README.txt`. O campo `split` separa `train`/`dev`/`test`: use `train` para desenvolvimento, `dev` para ajustes e `test` apenas na avaliação final.
