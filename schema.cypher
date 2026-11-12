// BankGraph AI - schema (Neo4j 5.x). Idempotente: pode rodar varias vezes.
CREATE CONSTRAINT customer_id  IF NOT EXISTS FOR (n:Customer)    REQUIRE n.customer_id IS UNIQUE;
CREATE CONSTRAINT account_id   IF NOT EXISTS FOR (n:Account)     REQUIRE n.account_id IS UNIQUE;
CREATE CONSTRAINT tx_id        IF NOT EXISTS FOR (n:Transaction) REQUIRE n.transaction_id IS UNIQUE;
CREATE CONSTRAINT loan_id      IF NOT EXISTS FOR (n:Loan)        REQUIRE n.loan_id IS UNIQUE;
CREATE CONSTRAINT card_id      IF NOT EXISTS FOR (n:Card)        REQUIRE n.card_id IS UNIQUE;
CREATE CONSTRAINT merchant_id  IF NOT EXISTS FOR (n:Merchant)    REQUIRE n.merchant_id IS UNIQUE;
CREATE CONSTRAINT branch_id    IF NOT EXISTS FOR (n:Branch)      REQUIRE n.branch_id IS UNIQUE;
CREATE CONSTRAINT employee_id  IF NOT EXISTS FOR (n:Employee)    REQUIRE n.employee_id IS UNIQUE;
CREATE CONSTRAINT alert_id     IF NOT EXISTS FOR (n:Alert)       REQUIRE n.alert_id IS UNIQUE;
CREATE CONSTRAINT complaint_id IF NOT EXISTS FOR (n:Complaint)   REQUIRE n.complaint_id IS UNIQUE;
CREATE CONSTRAINT document_id  IF NOT EXISTS FOR (n:Document)    REQUIRE n.document_id IS UNIQUE;
CREATE CONSTRAINT rule_id      IF NOT EXISTS FOR (n:BankingRule) REQUIRE n.rule_id IS UNIQUE;

CREATE INDEX tx_ts        IF NOT EXISTS FOR (t:Transaction) ON (t.timestamp);
CREATE INDEX tx_flagged   IF NOT EXISTS FOR (t:Transaction) ON (t.flagged);
CREATE INDEX loan_status  IF NOT EXISTS FOR (l:Loan)        ON (l.status);
CREATE INDEX alert_date   IF NOT EXISTS FOR (a:Alert)       ON (a.alert_date);

CREATE FULLTEXT INDEX merchant_text IF NOT EXISTS FOR (m:Merchant)    ON EACH [m.merchant_name, m.category];
CREATE FULLTEXT INDEX rule_text     IF NOT EXISTS FOR (r:BankingRule) ON EACH [r.rule_name, r.description];
CREATE FULLTEXT INDEX document_text IF NOT EXISTS FOR (d:Document)    ON EACH [d.title, d.text];

// Vetorial: ajuste vector.dimensions ao modelo (384 = all-MiniLM-L6-v2; 768 = multilingual-e5-base / paraphrase-multilingual-mpnet)
CREATE VECTOR INDEX document_embedding IF NOT EXISTS
FOR (d:Document) ON (d.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
CREATE VECTOR INDEX rule_embedding IF NOT EXISTS
FOR (r:BankingRule) ON (r.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
