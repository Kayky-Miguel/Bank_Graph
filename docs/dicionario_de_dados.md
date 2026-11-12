# Dicionário de dados — BankGraph AI

Gerado a partir dos CSVs de `BankGraph_AI_Dataset/`. **Todos os dados são sintéticos**: nomes, IDs e valores são inventados; não há CPF, número de conta ou cartão reais. Alertas e `flagged` são sinais simulados e **não comprovam fraude**.

Convenções: datas no formato `YYYY-MM-DD`; valores em reais (BRL); os dados terminam em **2026-11-10** (data de referência das consultas). Coluna *Valores*: lista completa quando há até 12 valores distintos; senão, um exemplo.

## Resumo

| Arquivo | Linhas | Vira no grafo | Conteúdo |
|---|---|---|---|
| `customers.csv` | 500 | Customer | Clientes fictícios. |
| `accounts.csv` | 823 | Account | Contas bancárias simuladas. |
| `account_owners.csv` | 868 | relação OWNS | Titularidade: liga cliente e conta (uma conta conjunta tem mais de um dono). |
| `transactions.csv` | 9749 | Transaction | Movimentações simuladas de uma conta para um estabelecimento. |
| `cards.csv` | 500 | Card | Cartões fictícios (sem número real). |
| `loans.csv` | 200 | Loan | Empréstimos simulados. |
| `merchants.csv` | 150 | Merchant | Estabelecimentos que recebem pagamentos. |
| `alerts.csv` | 100 | Alert | Alertas simulados sobre transações sinalizadas. Não comprovam fraude. |
| `complaints.csv` | 150 | Complaint | Reclamações simuladas de clientes. |
| `branches.csv` | 20 | Branch | Agências fictícias. |
| `employees.csv` | 60 | Employee | Funcionários fictícios. |
| `documents.csv` | 30 | Document | Documentos institucionais fictícios (10 textos em 3 versões). |
| `banking_rules.csv` | 30 | BankingRule | Regras explícitas extraídas dos documentos (uma por documento). |
| `evaluation_cases.csv` | 5 | (não vai para o grafo) | Casos de avaliação originais do dataset. |

## customers.csv → Customer

Clientes fictícios.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `customer_id` | ID do cliente (C0001...) | ex.: `C0001` (500 distintos) |  |
| `name` | Nome fictício | ex.: `Ana Almeida` (177 distintos) |  |
| `birth_year` | Ano de nascimento | ex.: `1958` (47 distintos) |  |
| `city` | Cidade | `Campina Grande`, `Fortaleza`, `João Pessoa`, `Maceió`, `Natal`, `Recife`, `Salvador` |  |
| `state` | UF | `AL`, `BA`, `CE`, `PB`, `PE`, `RN` |  |
| `segment` | Segmento do cliente | `BASIC`, `PREMIUM`, `STANDARD` |  |
| `monthly_income_brl` | Renda mensal simulada (R$) | `10000`, `15000`, `1800`, `2500`, `3500`, `5000`, `7000` |  |
| `registration_date` | Data de cadastro | ex.: `2019-01-05` (444 distintos) |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test`, `train` |  |

## accounts.csv → Account

Contas bancárias simuladas.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `account_id` | ID da conta (A0001...) | ex.: `A0001` (823 distintos) |  |
| `account_type` | Tipo de conta | `CHECKING`, `PAYMENT`, `SAVINGS` |  |
| `status` | Situação do registro | `ACTIVE`, `BLOCKED`, `CLOSED` |  |
| `opened_date` | Data de abertura | ex.: `2019-01-01` (592 distintos) |  |
| `simulated_balance_brl` | Saldo simulado (R$) | ex.: `1000` (701 distintos) |  |
| `branch_id` | ID da agência (B001...) | ex.: `B001` (20 distintos) |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test`, `train` |  |

## account_owners.csv → relação OWNS

Titularidade: liga cliente e conta (uma conta conjunta tem mais de um dono).

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `customer_id` | ID do cliente (C0001...) | ex.: `C0001` (500 distintos) |  |
| `account_id` | ID da conta (A0001...) | ex.: `A0001` (823 distintos) |  |
| `ownership_type` | PRIMARY = titular; JOINT = conta conjunta | `JOINT`, `PRIMARY` |  |

## transactions.csv → Transaction

Movimentações simuladas de uma conta para um estabelecimento.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `transaction_id` | ID da transação (T0000001...) | ex.: `T0000001` (9749 distintos) |  |
| `account_id` | ID da conta (A0001...) | ex.: `A0001` (821 distintos) |  |
| `merchant_id` | ID do estabelecimento (M0001...) | ex.: `M0001` (150 distintos) |  |
| `amount_brl` | Valor (R$) | ex.: `10.41` (9542 distintos) |  |
| `transaction_type` | Tipo de transação | `BILL_PAYMENT`, `CARD_PURCHASE`, `PIX_TRANSFER`, `TED_TRANSFER`, `WITHDRAWAL` |  |
| `transaction_date` | Data (vira `date` no grafo) | ex.: `2024-11-10` (731 distintos) |  |
| `transaction_time` | Hora (com a data vira `timestamp`) | ex.: `00:00:00` (1439 distintos) |  |
| `status` | Situação do registro | `COMPLETED`, `PENDING`, `REVERSED` |  |
| `channel` | Canal | `APP`, `ATM`, `POS`, `WEB` |  |
| `flagged` | Sinalizada pelo cenário simulado (não comprova fraude) | `False`, `True` |  |
| `scenario` | Cenário que gerou a transação (controle dos casos de teste) | `MERCHANT_CONCENTRATION`, `NORMAL`, `RECURRING_TRANSFER`, `SIMULATED_ALERT` |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test`, `train` |  |

## cards.csv → Card

Cartões fictícios (sem número real).

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `card_id` | ID do cartão (CC0001...) | ex.: `CC0001` (500 distintos) |  |
| `customer_id` | ID do cliente (C0001...) | ex.: `C0001` (315 distintos) |  |
| `account_id` | ID da conta (A0001...) | ex.: `A0001` (353 distintos) |  |
| `brand` | Bandeira | `ELO`, `MASTERCARD`, `VISA` |  |
| `card_type` | Crédito ou débito | `CREDIT`, `DEBIT` |  |
| `credit_limit_brl` | Limite (R$) | `0`, `1000`, `2000`, `3500`, `5000`, `8000` |  |
| `status` | Situação do registro | `ACTIVE`, `BLOCKED` |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test`, `train` |  |

## loans.csv → Loan

Empréstimos simulados.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `loan_id` | ID do empréstimo (L0001...) | ex.: `L0001` (200 distintos) |  |
| `customer_id` | ID do cliente (C0001...) | ex.: `C0001` (175 distintos) |  |
| `account_id` | ID da conta (A0001...) | ex.: `A0004` (182 distintos) |  |
| `principal_brl` | Valor contratado (R$) | ex.: `10116.45` (200 distintos) |  |
| `annual_interest_rate_pct` | Juros ao ano (%) | ex.: `10.05` (192 distintos) |  |
| `installments_total` | Total de parcelas | `12`, `18`, `24`, `36`, `48`, `6`, `60` |  |
| `installments_paid` | Parcelas pagas | ex.: `0` (45 distintos) |  |
| `status` | Situação do registro | `ACTIVE`, `CANCELLED`, `LATE`, `PAID` |  |
| `start_date` | Início do contrato | ex.: `2021-01-13` (193 distintos) |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test`, `train` |  |

## merchants.csv → Merchant

Estabelecimentos que recebem pagamentos.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `merchant_id` | ID do estabelecimento (M0001...) | ex.: `M0001` (150 distintos) |  |
| `merchant_name` | Nome fictício do estabelecimento | ex.: `Central Brasil` (30 distintos) |  |
| `category` | Categoria | `Combustível`, `Educação`, `Farmácia`, `Restaurante`, `Saúde`, `Serviços`, `Supermercado`, `Tecnologia`, `Transporte`, `Varejo` |  |
| `city` | Cidade | `Campina Grande`, `Fortaleza`, `João Pessoa`, `Maceió`, `Natal`, `Recife`, `Salvador` |  |
| `state` | UF | `AL`, `BA`, `CE`, `PB`, `PE`, `RN` |  |
| `risk_profile` | Perfil de risco simulado | `HIGH`, `LOW`, `MEDIUM` |  |
| `active` | Estabelecimento ativo | `True` |  |

## alerts.csv → Alert

Alertas simulados sobre transações sinalizadas. Não comprovam fraude.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `alert_id` | ID do alerta (AL00001...) | ex.: `AL00001` (100 distintos) |  |
| `transaction_id` | ID da transação (T0000001...) | ex.: `T0000252` (100 distintos) |  |
| `alert_type` | Tipo de alerta | `HIGH_FREQUENCY`, `RISKY_MERCHANT`, `UNUSUAL_AMOUNT`, `UNUSUAL_HOUR` |  |
| `severity` | Severidade | `HIGH`, `LOW`, `MEDIUM` |  |
| `alert_date` | Data do alerta | ex.: `2024-11-27` (92 distintos) |  |
| `status` | Situação do registro | `CLOSED`, `OPEN`, `UNDER_REVIEW` |  |
| `note` | Observação do alerta | ex.: `Alerta sintético; não comprova fraude.` (1 distintos) |  |

## complaints.csv → Complaint

Reclamações simuladas de clientes.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `complaint_id` | ID da reclamação (CP00001...) | ex.: `CP00001` (150 distintos) |  |
| `customer_id` | ID do cliente (C0001...) | ex.: `C0002` (133 distintos) |  |
| `transaction_id` | ID da transação (T0000001...) | ex.: `` (0 distintos) | 150 |
| `category` | Categoria | `CARD_PURCHASE`, `LOAN`, `SERVICE`, `TRANSFER` |  |
| `description` | Descrição | ex.: `Compra não reconhecida (simulada)` (4 distintos) |  |
| `status` | Situação do registro | `IN_PROGRESS`, `OPEN`, `RESOLVED` |  |
| `created_date` | Data de abertura | ex.: `2025-07-02` (126 distintos) |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test`, `train` |  |

## branches.csv → Branch

Agências fictícias.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `branch_id` | ID da agência (B001...) | ex.: `B001` (20 distintos) |  |
| `branch_name` | Nome da agência | ex.: `Agência Simulada 001` (20 distintos) |  |
| `city` | Cidade | `Campina Grande`, `Fortaleza`, `João Pessoa`, `Maceió`, `Natal`, `Recife`, `Salvador` |  |
| `state` | UF | `AL`, `BA`, `CE`, `PB`, `PE`, `RN` |  |

## employees.csv → Employee

Funcionários fictícios.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `employee_id` | ID do funcionário (E0001...) | ex.: `E0001` (60 distintos) |  |
| `employee_name` | Nome fictício | ex.: `Ana Oliveira` (52 distintos) |  |
| `branch_id` | ID da agência (B001...) | ex.: `B001` (16 distintos) |  |
| `role` | Função | `ANALYST`, `MANAGER`, `SERVICE` |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `train` |  |

## documents.csv → Document

Documentos institucionais fictícios (10 textos em 3 versões).

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `document_id` | ID do documento (DOC001...) | ex.: `DOC001` (30 distintos) |  |
| `title` | Título | ex.: `Atualização Cadastral - Documento 04` (30 distintos) |  |
| `document_type` | Tipo de documento | `GUIDELINE`, `POLICY`, `PROCEDURE` |  |
| `version` | Versão | `1`, `2` |  |
| `published_date` | Data de publicação | ex.: `2024-01-24` (30 distintos) |  |
| `section` | Seção (proveniência) | ex.: `1.1` (28 distintos) |  |
| `page` | Página (proveniência) | `1`, `10`, `11`, `12`, `2`, `3`, `4`, `5`, `7`, `8`, `9` |  |
| `text` | Texto do documento | ex.: `Bloqueios simulados devem registrar ju…` (10 distintos) |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test`, `train` |  |

## banking_rules.csv → BankingRule

Regras explícitas extraídas dos documentos (uma por documento).

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `rule_id` | ID da regra (R001...) | ex.: `R001` (30 distintos) |  |
| `document_id` | ID do documento (DOC001...) | ex.: `DOC001` (30 distintos) |  |
| `rule_name` | Tema da regra | `Atualização Cadastral`, `Bloqueio Preventivo`, `Concentração de Pagamentos`, `Conta Compartilhada`, `Contestação de Compra`, `Empréstimo Pessoal`, `Frequência de Transferências`, `Limite de Transferência PIX`, `Privacidade e Acesso`, `Transações Atípicas` |  |
| `description` | Descrição | ex.: `Bloqueios simulados devem registrar ju…` (10 distintos) |  |
| `applies_to` | A que a regra se aplica | `ACCOUNT`, `CUSTOMER`, `LOAN`, `TRANSACTION` |  |
| `severity` | Severidade | `INFO`, `RESTRICTED`, `REVIEW` |  |
| `is_active` | Regra vigente | `True` |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test`, `train` |  |

## evaluation_cases.csv → (não vai para o grafo)

Casos de avaliação originais do dataset.

| Campo | Descrição | Valores | Vazios |
|---|---|---|---|
| `case_id` | ID do caso | ex.: `Q001` (5 distintos) |  |
| `split` | Partição train/dev/test (uso em desenvolvimento x avaliação) | `dev`, `test` |  |
| `question` | Pergunta | ex.: `Quais clientes possuem contas conjuntas?` (5 distintos) |  |
| `expected_task` | O que a resposta deve fazer | ex.: `Agrupar transações por estabelecimento…` (5 distintos) |  |
| `answerable` | Se a pergunta tem resposta nos dados | `False`, `True` |  |

## Propriedades criadas pelo pipeline (não estão nos CSVs)

| Onde | Propriedade | Origem |
|---|---|---|
| Transaction | `timestamp`, `date` | `ingest.py` (data + hora) |
| Document, BankingRule | `embedding` (384 dimensões) | `embed_docs.py` |
| Entity (RuleTopic, Segment, Limit, Term, Condition, Action, Obligation) | `key`, `name`, `type` | `extract_entities.py` (Etapa 4) |
| Customer, Merchant | `pagerank`, `community` | `graph_algorithms.py` |
