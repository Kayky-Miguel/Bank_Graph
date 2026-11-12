# Escopo e requisitos — BankGraph AI

## 1. Problema

Informações bancárias ficam espalhadas entre registros estruturados (clientes, contas, transações, empréstimos) e documentos institucionais (regras, limites, procedimentos). Perguntas como *"quais clientes têm relação com contas que tiveram transações sinalizadas e, entre eles, quais têm empréstimo ativo?"* exigem conectar várias entidades e regras, algo que uma busca textual simples não faz.

## 2. Objetivo

Um assistente que responde perguntas em linguagem natural combinando:
- um **grafo de conhecimento no Neo4j** (modelo LPG) com dados estruturados e conhecimento extraído de documentos (Text-to-Graph);
- **recuperação híbrida**: busca vetorial, consultas Cypher controladas e regras explícitas (GraphRAG + KAG);
- respostas **fundamentadas**, com os nós, caminhos, consultas e trechos usados como evidência.

## 3. Escopo

**Caso principal:** análise de relacionamentos entre clientes, contas e transações potencialmente suspeitas (sinalizadas), incluindo relações indiretas (multi-hop).

**Casos secundários:** consulta de contas, cartões, empréstimos e regras bancárias documentadas; análise de rede (centralidade e comunidades).

**Fora do escopo:** integração com bancos ou contas reais; execução de transferências, bloqueios ou concessão de crédito; decisão automática de fraude ou de aprovação de empréstimo; internet banking.

**Regra de segurança:** somente dados sintéticos. Alertas e transações sinalizadas são **sinais simulados que merecem análise, não prova de fraude**.

## 4. Requisitos funcionais

| ID | Requisito | Implementação | Verificação |
|---|---|---|---|
| RF01 | Carregar os dados estruturados no Neo4j com IDs únicos e validar as contagens | `ingest.py`, `schema.cypher` | Validação ao final da ingestão (todas as linhas `OK`) |
| RF02 | Extrair entidades e relações dos documentos (NER/RE) com rastreabilidade ao documento | `extract_entities.py` | `evaluate_extraction.py --analysis` |
| RF03 | Resolver entidades duplicadas (30 regras → 10 temas canônicos) | `extract_entities.py` (`key`, `INSTANCE_OF`) | Consulta de checagem no README |
| RF04 | Buscar trechos e regras por similaridade semântica | `embed_docs.py`, índices vetoriais | Perguntas A04–A06 da avaliação |
| RF05 | Interpretar a pergunta e escolher uma consulta pronta ou gerar Cypher validado | `graphrag_pipeline.py` (`plan_query`, `validate_cypher`) | `test_etapa5.py`, `tests/test_pipeline.py` |
| RF06 | Percorrer caminhos multi-hop (relação indireta, caminho mínimo) | Templates `indirect_joint`, `path_between_customers` | Perguntas A02 e A07 |
| RF07 | Combinar fatos do grafo com regras explícitas (KAG) | `kag_rules`, template `customer_loans_rules` | Pergunta A03 |
| RF08 | Aplicar algoritmos de grafo (PageRank, comunidades, caminho mínimo) | `graph_algorithms.py`, templates de algoritmos | Pergunta A08, `tests/test_graph_algorithms.py` |
| RF09 | Responder somente com base nas evidências e se abster quando não houver | `generate_answer`, `guard`, limiar vetorial | Perguntas U01–U03, M01–M02, O01–O02 |
| RF10 | Mostrar resposta, confiança, IDs, fontes, Cypher executado e subgrafo | `app.py`, `graph_view.py`, `retrieval.py` | `tests/test_ui.py` (teste de ponta a ponta da interface) |
| RF11 | Avaliar respostas e extração com métricas reprodutíveis | `evaluate_qa.py`, `evaluate_extraction.py` | `evaluation/README.md` |

## 5. Requisitos não funcionais

| ID | Requisito | Como é atendido |
|---|---|---|
| RNF01 | **Somente leitura** nas consultas de resposta | Transações `execute_read`; validador barra CREATE/MERGE/SET/DELETE/CALL etc. |
| RNF02 | **Consultas limitadas** | Allowlist de labels e relações; profundidade ≤ 4 para Cypher do LLM; `LIMIT` ≤ 100; timeout de 15 s |
| RNF03 | **Sem IDs inventados** | Todo ID usado na consulta precisa estar na pergunta; IDs citados sem evidência são sinalizados |
| RNF04 | **Privacidade** | Dados sintéticos; pedidos de CPF/senha são recusados sem consultar o grafo |
| RNF05 | **Reprodutibilidade** | Grafo recriado por scripts; data de referência fixa (2026-11-10); semente fixa no Louvain; extração validada versionada (`--from-results`) |
| RNF06 | **Segredos fora do código** | Senhas e chaves só por variável de ambiente |
| RNF07 | **Latência de demonstração** | Alvo < 5 s por pergunta com LLM (medida na avaliação) |
| RNF08 | **Testável sem infraestrutura** | Testes automatizados sem Neo4j nem chave de API (`python -m pytest tests -q`) |

## 6. Perguntas de teste e critério de resposta correta

São 25 perguntas em `evaluate_qa.py`: 18 respondíveis (básicas, intermediárias e avançadas, incluindo multi-hop e algoritmos de grafo), 3 sem resposta, 2 ambíguas e 2 fora do domínio.

O **gabarito é calculado diretamente dos CSVs**, sem usar o Neo4j nem o código avaliado. Uma resposta é considerada correta quando:
- **respondível:** recupera pelo menos 80% dos IDs esperados, do tipo pedido, sem se abster. Perguntas sobre regras são comparadas por **tema**;
- **sem resposta, ambígua ou fora do domínio:** o sistema se abstém, ou dá a resposta conceitual exigida (ex.: "alerta não comprova fraude");
- **sempre:** sem erro de execução e sem dado proibido (ex.: CPF).

**Evidências que devem ser exibidas:** IDs dos nós citados, consulta Cypher com parâmetros, documentos e regras de origem (seção e página) e o subgrafo utilizado.

## 7. Critério de sucesso do projeto

Responder perguntas multi-hop com fatos corretos, mostrar caminhos e trechos usados, admitir quando não sabe e **demonstrar por avaliação que a recuperação híbrida supera a busca vetorial isolada**. Resultados em `evaluation/README.md`.
