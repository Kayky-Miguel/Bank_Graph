# Etapa 7 — Avaliação e testes

Situação: **concluída** (2026-11-12). Os resultados finais estão na seção 2 e em `report.md` / `results_*.json` desta pasta; as rodadas anteriores ficam nas subpastas, como histórico.

| Rodada | O que mediu | Onde |
|---|---|---|
| 1 | Baseline × vetorial, corte de similaridade com bug de escala | `rodada1/` |
| 2 | Baseline × vetorial, corte calibrado (23 perguntas) | `rodada2/` e seção 2.2 |
| 3 | Primeira com a Etapa 5 (23 perguntas, métrica antiga para regras) | `rodada3/` e seção 2.4 |
| 4 | Etapa 5 corrigida + algoritmos de grafo (25 perguntas), antes do replanejamento | `rodada4/` e seção 2.1 |
| **final** | Rodada 4 + replanejamento quando o LLM não escolhe consulta para pergunta com ID | `report.md` e `results_*.json` (esta pasta), seção 2.1 |

| Arquivo | Conteúdo | Como gerar |
|---|---|---|
| `extraction_errors.md` | NER/RE: métricas estrita e relaxada, erros classificados | `python evaluate_extraction.py --analysis` |
| `report.md` | Respostas: resumo, resultado por pergunta, falhas | `python evaluate_qa.py` |
| `results_<backend>.json` | Respostas brutas, IDs e métricas de cada pergunta | `python evaluate_qa.py` |

Testes automatizados (sem Neo4j): `python -m pytest tests -q`.

## 1. Extração de entidades e relações (Text-to-Graph)

Gabarito anotado à mão: DOC001–DOC010, um documento por tema.

| | Precisão | Recall | F1 |
|---|---|---|---|
| Entidades, estrita | 0,62 | 0,75 | 0,68 |
| Entidades, relaxada | 0,91 | 0,89 | 0,90 |
| Relações, estrita | 0,43 | 0,56 | 0,49 |
| Relações, relaxada | 0,87 | 0,78 | 0,82 |

A comparação **estrita** exige nome normalizado idêntico. A **relaxada** aceita como acerto duas divergências de forma: *enumeração separada* (o gabarito anota "justificativa, data e responsável" como um item e o LLM separa em três) e *variação de nome*. Tipo errado, omissão e item extra continuam contando como erro.

O que a análise mostra: a maior parte da distância entre estrita e relaxada é **convenção de granularidade**, não alucinação. Os erros reais concentram-se em:
- **omissões** de relações `MAY_TRIGGER` que partem de uma condição (DOC002, DOC004);
- **DOC005 (Conta Compartilhada)**, onde o LLM tratou "considerar todos os vínculos" como ação em vez de obrigação;
- **perda de qualificador**: "R$ 2.000 por dia" virou "R$ 2.000" (classificada como variação de nome, mas perde o período).

Nenhum item extraído foi inventado: os "extras" estão presentes no texto, só não foram anotados no gabarito.

## 2. Respostas (GraphRAG/KAG)

**Conjunto de perguntas** (`evaluate_qa.py`): 25 perguntas. São 18 respondíveis (5 básicas, 5 intermediárias, 8 avançadas, incluindo a pergunta central, as multi-hop, caminho mínimo e PageRank), 3 sem resposta, 2 ambíguas e 2 fora do domínio. As rodadas 1 a 3 usaram 23 perguntas (sem A07 e A08). Os 5 casos de `evaluation_cases.csv` estão incluídos.

**Gabarito independente**: as respostas esperadas são calculadas **direto dos CSVs com pandas**, sem Neo4j e sem o código avaliado. O gabarito foi conferido contra os valores do README: 7 clientes com transação sinalizada em 30 dias, sendo 3 com empréstimo ativo (C0208, C0234, C0410), e 4 clientes com relação indireta em 365 dias.

> Achado durante a montagem do gabarito: dois clientes (C0249 e C0306) aparecem num cálculo ingênuo de "relação indireta", mas são donos da própria conta sinalizada. A relação deles é **direta**. O Cypher já os exclui, porque um caminho não reutiliza o mesmo relacionamento `OWNS`, e o gabarito foi ajustado para refletir isso.

**Métricas**

| Métrica | O que mede | Item do plano |
|---|---|---|
| Precisão / recall / F1 dos IDs | Fatos corretos na resposta (só o tipo de ID pedido) | Correção das consultas e precisão factual |
| Tema correto nas 3 primeiras fontes | Recuperação documental (KAG) | Citações sustentam a resposta |
| Abstenção correta | Admitir insuficiência em perguntas sem resposta, ambíguas e fora do domínio | Perguntas sem resposta/ambíguas |
| Abstenção indevida | Abster-se quando havia resposta | Falhas de recuperação |
| Respostas com evidência | Resposta acompanhada de subgrafo, linhas ou fontes | Proveniência |
| ID sem suporte | ID citado no texto que não aparece nas evidências | Alucinação |
| Latência média / p95, erros | Desempenho | Latência e erros |

**Comparação** (critério de sucesso do plano): *busca vetorial isolada* (só índices vetoriais, sem travessia) contra o *baseline híbrido* (templates Cypher + vetorial + regras ligadas no grafo, sem LLM) e a *Etapa 5* (`graphrag_pipeline.py` via `retrieval.py`, com gpt-4o-mini).

### 2.1 Resultados finais (2026-11-12, 25 perguntas)

| Métrica | Vetorial isolada | Baseline híbrido | Etapa 5 (GraphRAG/KAG + LLM) |
|---|---|---|---|
| Acurácia geral (25) | 0,36 | 0,72 | **0,88** |
| Acurácia nas respondíveis (18) | 0,22 | 0,78 | **0,83** |
| Precisão / recall / F1 dos IDs | 0,11 / 0,22 / 0,15 | 0,61 / 0,78 / 0,66 | **0,72 / 0,83 / 0,76** |
| Tema correto nas 3 primeiras fontes | 1,00 | 1,00 | 1,00 |
| Abstenção correta (7 sem resposta/ambíguas/fora) | 0,71 | 0,57 | **1,00** |
| Abstenção indevida (respondíveis) | 0,17 | **0,06** | 0,11 |
| Respostas com evidência rastreável | 1,00 | 1,00 | 1,00 |
| Respostas com ID sem suporte | 0,00 | 0,00 | 0,00 |
| Erros de execução | 0 | 0 | 0 |
| Latência média / p95 | 54 / 61 ms | 59 / 143 ms | 3,4 / 5,5 s |

**Critério de sucesso atendido.** A recuperação híbrida supera a busca vetorial isolada em todas as métricas de fatos: 0,83 contra 0,22 nas respondíveis. A vetorial acerta o tema do documento em 100% dos casos, mas não acerta nenhuma pergunta estruturada, porque os documentos não contêm os fatos dos clientes.

**Etapa 5 contra o baseline.** A Etapa 5 é a melhor no geral (0,88 contra 0,72). Ela resolve o que o baseline, com roteamento fixo, não resolve: I05 (estabelecimento específico), A03 (regras do empréstimo de um cliente, KAG), A06 (pergunta sobre regra e não sobre dados), A08 (PageRank), U03 (recusa do CPF) e M01/M02 (pede o ID em vez de adivinhar). Acertou as 7 perguntas sem resposta, ambíguas e fora do domínio, e nenhuma resposta citou ID sem suporte. O custo é a latência, de cerca de 3,4 s por pergunta (dentro do alvo de 5 s), contra menos de 0,1 s do baseline.

**Evolução da Etapa 5:** rodada 3: 0,56 → rodada 4: 0,80 → final: **0,88**. Da rodada 4 para a final, o replanejamento (quando o LLM não escolhe consulta para uma pergunta com ID) recuperou B05 e A07; a abstenção indevida caiu de 0,28 para 0,11; o falso alarme de ID sem suporte (0,08) sumiu com a nova mensagem de pedido de ID.

**Falhas restantes da Etapa 5** (registradas sem ajuste, para não calibrar o sistema olhando a avaliação):

| Pergunta | O que aconteceu | Causa |
|---|---|---|
| B01 contas do C0208, B02 empréstimos ativos do C0208 | Absteve-se | O LLM devolveu "nenhuma consulta" nas duas tentativas, mesmo com o aviso de que a pergunta tem ID. A pergunta equivalente B03 (contas do C0001) acertou: o planejador não é determinístico. |
| B04 cartões do C0352 | Resposta certa (3 cartões, bandeira, limite, situação), mas sem os IDs | O LLM escreveu o próprio Cypher e não devolveu `card_id`. É uma limitação da métrica, que compara IDs. |

Uma correção possível, sem depender do LLM, é cair para o template do tipo de ID da pergunta (cliente → `customer_accounts`) quando o planejador recusar duas vezes.

Detalhe por pergunta em `report.md`; respostas brutas, Cypher e planos do LLM em `results_*.json`.

### 2.2 Histórico: rodada 2, baseline × vetorial (23 perguntas)

| Métrica | Baseline híbrido | Vetorial isolada |
|---|---|---|
| Acurácia geral (23 perguntas) | **0,74** | 0,39 |
| Acurácia nas respondíveis (16) | **0,81** | 0,25 |
| Precisão / recall / F1 dos IDs | **0,66 / 0,81 / 0,71** | 0,15 / 0,25 / 0,19 |
| Tema correto nas 3 primeiras fontes | 1,00 | 1,00 |
| Abstenção correta (7 sem resposta/ambíguas/fora) | 0,57 | **0,71** |
| Abstenção indevida (respondíveis) | 0,06 | 0,12 |
| Respostas com evidência rastreável | 1,00 | 1,00 |
| Respostas com ID sem suporte | 0,00 | 0,00 |
| Erros de execução | 0 | 0 |
| Latência média / p95 | 51 / 77 ms | 107 / 162 ms |

Detalhe por pergunta em `rodada2/report.md`.

**O grafo agrega valor.** Nas perguntas estruturadas e multi-hop (contas, empréstimos, cartões, transações, contas conjuntas, relação indireta, pergunta central), a busca vetorial isolada **não acerta nenhuma**: ela encontra o documento do tema ("Conta Compartilhada", "Empréstimo Pessoal"), mas os documentos não contêm os fatos dos clientes. O baseline acerta todas essas. Nas perguntas sobre regras, as duas empatam (tema correto em 100%), ou seja, o ganho vem da travessia, não de recuperar documentos melhor.

**Nenhuma alucinação medida.** Nenhum ID citado nas respostas deixou de aparecer nas evidências. Isso é esperado num baseline sem LLM, cujas respostas são montadas por template a partir das consultas. A métrica fica como controle para a Etapa 5.

**Por que a precisão do baseline é 0,66 com recall 0,81** (nenhum caso é fato errado; são excessos de contexto):
- I04 e A02: a resposta cita mais clientes do que a pergunta pede (os 7 com transação sinalizada antes dos 3 com empréstimo; os intermediários "X via Y" da relação indireta).
- I03: ranking de 10 estabelecimentos, e o gabarito considera os 5 primeiros.
- A04 e A05: as 5 fontes trazem 2 regras de outro tema junto com as 3 corretas.

**Falhas do baseline** (requisitos para a Etapa 5):

| Pergunta | O que acontece | O que falta |
|---|---|---|
| I05 clientes que pagaram ao M0007 | Sem template; cai na busca de documentos e se abstém | Consulta por estabelecimento específico |
| A03 regras do empréstimo do C0208 | Responde contas e empréstimos, sem regras | Caminho Cliente → Loan → FOLLOWS → BankingRule ← Document (existe em `queries.cypher`) |
| A06 "o que acontece quando há concentração..." | Roteada para o ranking de estabelecimentos | Distinguir pergunta sobre regra de pergunta sobre dados |
| U03 CPF do cliente | Responde as contas | Recusar dados que o grafo não guarda (CPF etc.) |
| M01 / M02 "o cliente" / "dele" | Responde com documentos | Pedir o ID do cliente |

As falhas não foram corrigidas no baseline de propósito: ajustá-lo olhando as mesmas perguntas da avaliação inflaria a comparação.

### 2.3 Histórico: rodada 1 e correção de calibração

A rodada 1 (`rodada1/`) teve a mesma acurácia nas respondíveis (0,81 contra 0,25), mas o baseline **não se absteve** em perguntas fora do domínio ("Qual é a capital da França?" foi respondida com regras de contestação de compra). Causa: o índice vetorial do Neo4j devolve `score = (1 + cosseno) / 2`, então um texto **sem relação** já tem score ≈ 0,5, e o corte de 0,45 nunca bloqueava nada.

Calibração com o mesmo modelo de embeddings: perguntas fora do domínio têm cosseno ≈ 0,10 (score 0,55); perguntas reais sobre regras têm cosseno ≥ 0,51 (score ≥ 0,75). O corte passou para cosseno 0,30 (**score 0,65**), no meio do intervalo. Efeito na rodada 2: abstenção correta do baseline de 0,29 para 0,57, sem abstenção indevida nas perguntas sobre regras.

Observação: as latências da rodada 1 (média 281 ms) foram maiores por cache frio do Neo4j logo após a carga. Os valores da rodada 2 são os representativos.

### 2.4 Histórico: rodada 3, primeira avaliação da Etapa 5 e causas das falhas

Etapa 5 (gpt-4o-mini) nas 23 perguntas: acurácia geral 0,56 (baseline 0,74), respondíveis 0,44 (baseline 0,81), **abstenção correta 0,86** (baseline 0,57), nenhum ID sem suporte, latência média 3,4 s. A análise de cada falha encontrou estas causas, todas corrigidas depois:

| Falha | Causa | Correção |
|---|---|---|
| A04, A05, A06 marcadas como erro com resposta certa | **Métrica**: cada regra tem 3 cópias idênticas e o gabarito exigia as 3 | Perguntas sobre regras comparadas por tema |
| B04, I02, I05: consulta devolveu linhas, mas a resposta se absteve | `SCHEMA_TEXT` sem as propriedades de `Card` e com `ownership_type 'SOLE'` (não existe; é `PRIMARY`): o LLM adivinhava nomes e recebia só nulos | Schema completo conferido nos CSVs; consulta só com nulos ganha nova tentativa |
| I01 respondida com a relação indireta | Não havia consulta pronta para listar contas conjuntas | Templates `joint_accounts` e `joint_accounts_active_loan` |
| B05 "não há evidência" | `flagged_evidence` não filtra a transação pedida | Template `transaction_evidence` |
| A01 omitiu 4 dos 7 clientes | LLM omite itens de listas longas | Lista completa de IDs anexada pelo código |
| M02 respondeu sobre um cliente qualquer | O LLM ignorou a instrução de não inventar; além disso, um template sem ID usava o ID de exemplo em silêncio | Proteção sem LLM para "o cliente"/"dele" sem ID; todo ID da consulta precisa estar na pergunta |

Depois das correções, a Etapa 5 ganhou também consultas de **algoritmos de grafo** (caminho mínimo, PageRank, comunidades) e a avaliação, as perguntas A07 e A08. O efeito está na seção 2.1.

## 3. Limitações conhecidas

- Os 30 documentos são 10 textos idênticos em 3 versões. A extração dos splits dev/test é igual à do train, então não há avaliação independente por split.
- O gabarito NER/RE foi anotado por uma única pessoa, sem medida de concordância entre anotadores.
- As métricas de resposta comparam IDs, não o texto livre. Uma resposta com os IDs certos e uma explicação errada passaria. A checagem de frases cobre só casos específicos (ex.: "não comprova fraude").
- O baseline não tem LLM: o roteamento é por palavras-chave. Falhas esperadas: pergunta sobre um estabelecimento específico, regras aplicáveis a um cliente, pedido de CPF e perguntas ambíguas. A Etapa 5 resolve todos esses casos (seção 2.1).
- Dados 100% sintéticos: sinalização e alerta não comprovam fraude.
