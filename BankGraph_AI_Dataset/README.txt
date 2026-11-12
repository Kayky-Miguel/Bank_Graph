BANKGRAPH AI — DATASET SINTÉTICO

Arquivos: customers, accounts, account_owners, transactions, cards, loans, merchants, documents, banking_rules, alerts, complaints, branches, employees e evaluation_cases (todos CSV).

Chaves/relacionamentos: account_owners conecta Customer e Account; transactions conecta Account e Merchant; cards e loans conectam Customer e Account; banking_rules conecta Document; alerts conecta Transaction; complaints conecta Customer.

O campo split separa train/dev/test. Use train para desenvolvimento, dev para ajustes e test apenas na avaliação final. Os documentos são fictícios e curtos; para medir NER/RE, crie uma amostra anotada manualmente. Valores monetários em BRL. Datas YYYY-MM-DD. IDs sintéticos.

Todos os dados são inventados. Alertas e flagged=true são sinais simulados e NÃO comprovam fraude. Dataset destinado a testes acadêmicos, não representa estatisticamente o sistema bancário brasileiro.
