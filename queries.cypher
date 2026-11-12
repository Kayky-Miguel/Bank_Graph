// BankGraph AI - consultas de validacao e demo.
// Os dados vao ate 2026-11-10: use uma data de referencia FIXA, nao datetime().
// Em Neo4j Browser: :param ref => date('2026-11-10')   (ou passe como parametro no driver)

// ---------- Q001: clientes com conta conjunta (esperado: 45 contas) ----------
MATCH (c:Customer)-[o:OWNS {ownership_type:'JOINT'}]->(a:Account)
RETURN c.customer_id, c.name, a.account_id;

// ---------- Basica: contas e emprestimos ativos de um cliente ----------
MATCH (c:Customer {customer_id:'C0208'})-[:OWNS]->(a:Account) RETURN a.account_id, a.account_type, a.status;
MATCH (c:Customer {customer_id:'C0208'})-[:HAS_LOAN]->(l:Loan {status:'ACTIVE'}) RETURN l.loan_id, l.principal_brl;

// ---------- Q003: estabelecimentos que concentram pagamentos de varios clientes ----------
// (esperado: M0001 lidera com ~103 clientes distintos)
MATCH (c:Customer)-[:OWNS]->(:Account)-[:SENT]->(:Transaction)-[:PAID_TO]->(m:Merchant)
RETURN m.merchant_id, m.merchant_name, count(DISTINCT c) AS clientes
ORDER BY clientes DESC LIMIT 10;

// ---------- Q002 / PERGUNTA CENTRAL, nivel 1 (relacao direta) ----------
// Clientes donos de contas com transacao sinalizada nos ultimos 30 dias + emprestimo ativo.
// Esperado (ref 2026-11-10): 7 clientes com sinal; 3 com emprestimo ativo: C0208, C0234, C0410.
MATCH (c:Customer)-[:OWNS]->(a:Account)-[:SENT]->(t:Transaction {flagged:true})
WHERE t.date >= $ref - duration('P30D')
OPTIONAL MATCH (t)<-[:RAISED_ON]-(al:Alert)
OPTIONAL MATCH (c)-[:HAS_LOAN]->(l:Loan {status:'ACTIVE'})
RETURN c.customer_id, a.account_id, t.transaction_id, t.amount_brl,
       collect(DISTINCT al.alert_type) AS alertas, collect(DISTINCT l.loan_id) AS emprestimos_ativos
ORDER BY c.customer_id;

// ---------- PERGUNTA CENTRAL, nivel 2 (MULTI-HOP: relacao INDIRETA via conta conjunta) ----------
// Cliente X divide uma conta conjunta com um cliente Y que e dono de conta com transacao sinalizada.
// No dataset so ha poucos casos; com janela de 365 dias: 4 clientes indiretos (nenhum com emprestimo ativo);
// com 800 dias: 11 (2 com emprestimo ativo). Ajuste $dias.
MATCH p = (x:Customer)-[:OWNS]->(:Account)<-[:OWNS]-(y:Customer)-[:OWNS]->(:Account)-[:SENT]->(t:Transaction {flagged:true})
WHERE x <> y AND t.date >= $ref - duration({days: $dias})
OPTIONAL MATCH (x)-[:HAS_LOAN]->(l:Loan {status:'ACTIVE'})
RETURN x.customer_id AS cliente_indireto, y.customer_id AS via_cliente, t.transaction_id,
       collect(DISTINCT l.loan_id) AS emprestimos_ativos, p
LIMIT 50;

// ---------- Avancada: por que esta transacao foi sinalizada? (rastreabilidade) ----------
MATCH (al:Alert)-[:RAISED_ON]->(t:Transaction {flagged:true})<-[:SENT]-(a:Account)<-[:OWNS]-(c:Customer)
MATCH (t)-[:PAID_TO]->(m:Merchant)
RETURN t.transaction_id, al.alert_type, al.severity, al.alert_date, t.amount_brl, m.merchant_name, m.risk_profile,
       a.account_id, c.customer_id, al.note
LIMIT 10;

// ---------- KAG: regras aplicaveis ao emprestimo de um cliente + documento de origem ----------
MATCH (c:Customer {customer_id:'C0208'})-[:HAS_LOAN]->(l:Loan)-[:FOLLOWS]->(r:BankingRule)<-[:DESCRIBES]-(d:Document)
RETURN l.loan_id, r.rule_id, r.rule_name, r.description, d.document_id, d.title, d.section, d.page;

// ---------- Busca full-text em regras ----------
CALL db.index.fulltext.queryNodes('rule_text', 'transferência recorrente') YIELD node, score
RETURN node.rule_id, node.rule_name, score ORDER BY score DESC LIMIT 5;

// ---------- Busca hibrida (depois de gravar embeddings em Document.embedding) ----------
// CALL db.index.vector.queryNodes('document_embedding', 5, $query_embedding) YIELD node AS d, score
// OPTIONAL MATCH (d)-[:DESCRIBES]->(r:BankingRule)
// RETURN d.document_id, d.title, d.page, r.rule_id, r.rule_name, score;
