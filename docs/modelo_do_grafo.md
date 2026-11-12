# Modelo do grafo (LPG no Neo4j)

O diagrama abaixo é renderizado automaticamente pelo GitHub (Mermaid). Para o artigo, abra este arquivo no GitHub e capture a imagem, ou cole o bloco em <https://mermaid.live> e exporte como PNG/SVG.

## Dados estruturados (Etapas 2 e 3)

```mermaid
flowchart LR
    Customer(["Customer<br/>customer_id, segment,<br/>monthly_income_brl,<br/>pagerank, community"])
    Account(["Account<br/>account_id, account_type,<br/>status, simulated_balance_brl"])
    Transaction(["Transaction<br/>transaction_id, amount_brl,<br/>date, flagged, scenario"])
    Merchant(["Merchant<br/>merchant_id, category,<br/>risk_profile, pagerank, community"])
    Alert(["Alert<br/>alert_id, alert_type, severity"])
    Loan(["Loan<br/>loan_id, principal_brl, status"])
    Card(["Card<br/>card_id, brand, credit_limit_brl"])
    Branch(["Branch<br/>branch_id"])
    Employee(["Employee<br/>employee_id, role"])
    Complaint(["Complaint<br/>complaint_id, category, status"])

    Customer -- "OWNS {ownership_type}" --> Account
    Account -- SENT --> Transaction
    Transaction -- PAID_TO --> Merchant
    Alert -- RAISED_ON --> Transaction
    Customer -- HAS_LOAN --> Loan
    Loan -- ON_ACCOUNT --> Account
    Customer -- HAS_CARD --> Card
    Card -- LINKED_TO --> Account
    Account -- BELONGS_TO --> Branch
    Employee -- WORKS_AT --> Branch
    Customer -- FILED --> Complaint
    Complaint -- ABOUT --> Transaction
```

## Conhecimento (Etapa 4, Text-to-Graph, e KAG)

```mermaid
flowchart LR
    Document(["Document<br/>document_id, title, section,<br/>page, text, embedding"])
    BankingRule(["BankingRule<br/>rule_id, rule_name,<br/>description, embedding"])
    RuleTopic(["RuleTopic : Entity<br/>name"])
    Entity(["Segment | Limit | Term |<br/>Condition | Action | Obligation<br/>(Entity)"])
    Loan(["Loan"])

    Document -- DESCRIBES --> BankingRule
    Loan -- FOLLOWS --> BankingRule
    BankingRule -- INSTANCE_OF --> RuleTopic
    Document -- MENTIONS --> Entity
    RuleTopic -- "APPLIES_TO | HAS_LIMIT | HAS_TERM |<br/>REQUIRES | MAY_TRIGGER | MUST_RECORD" --> Entity
```

## Decisões de modelagem

| Decisão | Motivo |
|---|---|
| Transação é **nó**, não aresta | Permite ligar alerta, reclamação e estabelecimento à transação, filtrar por data e rastrear a origem (multi-hop). |
| Só existe `SENT` (conta → transação) | As transações do dataset não têm conta de destino, só estabelecimento (`PAID_TO`). |
| Titularidade na aresta `OWNS {ownership_type}` | Conta conjunta = mais de um `OWNS` para a mesma conta; é o caminho da "relação indireta" entre clientes. |
| `Loan -[:FOLLOWS]-> BankingRule` por heurística | Todo empréstimo segue as regras ativas "Empréstimo Pessoal" (o dataset não traz esse vínculo). |
| 30 regras → 10 temas (`INSTANCE_OF`) | Os 30 documentos são 10 textos em 3 versões; o tema canônico evita duplicar conhecimento (resolução de entidades). |
| `pagerank` e `community` como propriedades | Resultado dos algoritmos de grafo (`graph_algorithms.py`), consultável por Cypher e pelo LLM. |

## Índices e restrições

| Tipo | Onde | Criado por |
|---|---|---|
| Unicidade (constraint) | IDs de todos os 12 labels de negócio | `schema.cypher` |
| Unicidade (constraint) | `Entity.key` | `extract_entities.py` |
| B-tree | `Transaction.timestamp`, `Transaction.flagged`, `Loan.status`, `Alert.alert_date` | `schema.cypher` |
| B-tree | `Customer.community`, `Merchant.community` | `graph_algorithms.py` |
| Full-text | `Merchant(merchant_name, category)`, `BankingRule(rule_name, description)`, `Document(title, text)` | `schema.cypher` |
| Vetorial (384 dim, cosseno) | `Document.embedding`, `BankingRule.embedding` | `schema.cypher` |

## Volumes

500 clientes, 823 contas, 868 titularidades (45 conjuntas), 9.749 transações (100 sinalizadas), 100 alertas, 200 empréstimos, 500 cartões, 150 estabelecimentos, 20 agências, 60 funcionários, 150 reclamações, 30 documentos, 30 regras, 34 entidades extraídas e 23 relações extraídas.
