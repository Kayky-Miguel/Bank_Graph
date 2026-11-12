# Avaliacao das respostas - BankGraph AI

Gerado em 2026-11-12 12:02. Data de referencia dos dados: 2026-11-10. 23 perguntas; gabarito calculado direto dos CSVs (evaluate_qa.py).

## Resumo

| Metrica | baseline | vector |
|---|---|---|
| Acuracia geral | 0.65 | 0.22 |
| Acuracia (respondiveis) | 0.81 | 0.25 |
| Precisao dos IDs | 0.66 | 0.15 |
| Recall dos IDs | 0.81 | 0.25 |
| F1 dos IDs | 0.71 | 0.19 |
| Tema correto nas 3 primeiras fontes | 1.00 | 1.00 |
| Abstencao correta (sem resposta/ambigua/fora) | 0.29 | 0.14 |
| Abstencao indevida (respondiveis) | 0.00 | 0.00 |
| Respostas com evidencia rastreavel | 1.00 | 1.00 |
| Respostas com ID sem suporte | 0.00 | 0.00 |
| Erros de execucao | 0 | 0 |
| Latencia media (ms) | 281 | 71 |
| Latencia p95 (ms) | 704 | 89 |

## Por pergunta

| ID | Tipo | Pergunta | baseline | vector |
|---|---|---|---|---|
| B01 | answerable | Quais contas pertencem ao cliente C0208? | ok (P 1.00 / R 1.00) | falha (P 0.00 / R 0.00) |
| B02 | answerable | Quais empréstimos do cliente C0208 estão ativos? | ok (P 1.00 / R 1.00) | falha (P 0.00 / R 0.00) |
| B03 | answerable | Quais contas pertencem ao cliente C0001? | ok (P 1.00 / R 1.00) | falha (P 0.00 / R 0.00) |
| B04 | answerable | Quais cartões o cliente C0352 possui? | ok (P 1.00 / R 1.00) | falha (P 0.00 / R 0.00) |
| B05 | answerable | Por quais evidências a transação T0001050 foi sinalizada? | ok (P 1.00 / R 1.00) | falha (P 0.00 / R 0.00) |
| I01 | answerable | Quais clientes possuem contas conjuntas? | ok (P 1.00 / R 1.00) | falha (P 0.00 / R 0.00) |
| I02 | answerable | Quais clientes têm conta conjunta e empréstimo ativo? | ok (P 1.00 / R 1.00) | falha (P 0.00 / R 0.00) |
| I03 | answerable | Quais estabelecimentos concentram pagamentos de vários clientes? | ok (P 0.50 / R 1.00) | falha (P 0.00 / R 0.00) |
| I04 | answerable | Quais clientes têm empréstimos ativos e alertas simulados nos últimos 30 dias? | ok (P 0.43 / R 1.00) | falha (P 0.00 / R 0.00) |
| I05 | answerable | Quais clientes pagaram ao estabelecimento M0007? | falha (P 0.00 / R 0.00) | falha (P 0.00 / R 0.00) |
| A01 | answerable | Quais clientes possuem relacionamento com contas que realizaram transações sinalizadas nos últimos 30 dias e, entre eles, quais possuem empréstimos ativos? | ok (P 1.00 / R 1.00) | falha (P 0.00 / R 0.00) |
| A02 | answerable | Quais clientes têm relação indireta, por conta conjunta, com contas que tiveram transações sinalizadas nos últimos 365 dias? | ok (P 0.50 / R 1.00) | falha (P 0.00 / R 0.00) |
| A03 | answerable | Quais regras documentadas se aplicam ao empréstimo do cliente C0208? | falha (P 0.00 / R 0.00) | ok (P 0.60 / R 1.00) |
| A04 | answerable | Quais regras orientam a revisão de transferências recorrentes? | ok (P 0.60 / R 1.00) | ok (P 0.60 / R 1.00) |
| A05 | answerable | Qual é o limite do PIX para o segmento BASIC? | ok (P 0.60 / R 1.00) | ok (P 0.60 / R 1.00) |
| A06 | answerable | O que acontece quando há concentração de pagamentos em um estabelecimento? | falha (P 0.00 / R 0.00) | ok (P 0.60 / R 1.00) |
| U01 | unanswerable | Um alerta permite afirmar que houve fraude? | ok | ok |
| U02 | unanswerable | Quais contas pertencem ao cliente C9999? | ok (absteve) | falha |
| U03 | unanswerable | Qual é o CPF do cliente C0001? | falha | falha |
| M01 | ambiguous | Quais contas pertencem ao cliente? | falha | falha |
| M02 | ambiguous | E os empréstimos dele, estão ativos? | falha | falha |
| O01 | out_of_domain | Qual a previsão do tempo para amanhã em Maceió? | falha | falha |
| O02 | out_of_domain | Qual é a capital da França? | falha | falha |

## Falhas para analise

- **baseline / I05**: missing=['C0001', 'C0007', 'C0015', 'C0024', 'C0041', 'C0042', 'C0048', 'C0051', 'C0052', 'C0068', 'C0081', 'C0088', 'C0089', 'C0097', 'C0099']
- **baseline / A03**: missing=['R003', 'R013', 'R023']
- **baseline / A06**: missing=['R007', 'R017', 'R027']
- **baseline / U03**: ver results_baseline.json
- **baseline / M01**: ver results_baseline.json
- **baseline / M02**: ver results_baseline.json
- **baseline / O01**: ver results_baseline.json
- **baseline / O02**: ver results_baseline.json
- **vector / B01**: missing=['A0525', 'A0689']
- **vector / B02**: missing=['L0041']
- **vector / B03**: missing=['A0309']
- **vector / B04**: missing=['CC0001', 'CC0015', 'CC0234']
- **vector / B05**: missing=['AL00001']
- **vector / I01**: missing=['C0002', 'C0015', 'C0018', 'C0027', 'C0034', 'C0058', 'C0070', 'C0081', 'C0083', 'C0103', 'C0108', 'C0129', 'C0142', 'C0161', 'C0169']
- **vector / I02**: missing=['C0018', 'C0103', 'C0169', 'C0260', 'C0266', 'C0361', 'C0384', 'C0438', 'C0466']
- **vector / I03**: missing=['M0001', 'M0023', 'M0037', 'M0045', 'M0048']
- **vector / I04**: missing=['C0208', 'C0234', 'C0410']
- **vector / I05**: missing=['C0001', 'C0007', 'C0015', 'C0024', 'C0041', 'C0042', 'C0048', 'C0051', 'C0052', 'C0068', 'C0081', 'C0088', 'C0089', 'C0097', 'C0099']
- **vector / A01**: missing=['C0159', 'C0208', 'C0234', 'C0326', 'C0369', 'C0410', 'C0443', 'L0041', 'L0120', 'L0157']
- **vector / A02**: missing=['C0218', 'C0248', 'C0382', 'C0474']
- **vector / U02**: ver results_vector.json
- **vector / U03**: ver results_vector.json
- **vector / M01**: ver results_vector.json
- **vector / M02**: ver results_vector.json
- **vector / O01**: ver results_vector.json
- **vector / O02**: ver results_vector.json

Observacoes: as metricas de IDs comparam so o tipo de ID pedido pela pergunta. 'ID sem suporte' = ID citado no texto da resposta que nao aparece no subgrafo, nas linhas nem nas fontes (proxy de alucinacao). Dados sinteticos: sinalizacao nao comprova fraude.
