"""BankGraph AI - ingestao dos CSVs no Neo4j.

Uso:
  pip install neo4j pandas
  export NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io  NEO4J_USER=neo4j  NEO4J_PASSWORD=...
  python ingest.py --data ./BankGraph_AI_Dataset            # schema + carga + validacao
  python ingest.py --data ./BankGraph_AI_Dataset --dry-run  # so le/valida os CSVs, sem Neo4j
  python ingest.py --data ./BankGraph_AI_Dataset --wipe     # apaga o grafo antes (cuidado)
"""
import argparse, os, re, sys
from pathlib import Path
import pandas as pd

def read(data, name):
    df = pd.read_csv(Path(data) / f"{name}.csv", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    return df

def rows(df):
    """DataFrame -> lista de dicts; string vazia vira None (null no Neo4j)."""
    return [{k: (v if v != "" else None) for k, v in r.items()} for r in df.to_dict("records")]

# (nome, csv, cypher). Ordem importa: nos "pais" -> nos dependentes -> relacionamentos.
STEPS = [
 ("Branch", "branches", """
  UNWIND $rows AS r MERGE (b:Branch {branch_id: r.branch_id})
  SET b.branch_name=r.branch_name, b.city=r.city, b.state=r.state"""),
 ("Merchant", "merchants", """
  UNWIND $rows AS r MERGE (m:Merchant {merchant_id: r.merchant_id})
  SET m.merchant_name=r.merchant_name, m.category=r.category, m.city=r.city, m.state=r.state,
      m.risk_profile=r.risk_profile, m.active=(r.active='True')"""),
 ("Customer", "customers", """
  UNWIND $rows AS r MERGE (c:Customer {customer_id: r.customer_id})
  SET c.name=r.name, c.birth_year=toInteger(r.birth_year), c.city=r.city, c.state=r.state,
      c.segment=r.segment, c.monthly_income_brl=toFloat(r.monthly_income_brl),
      c.registration_date=date(r.registration_date), c.split=r.split"""),
 ("Account + BELONGS_TO", "accounts", """
  UNWIND $rows AS r MERGE (a:Account {account_id: r.account_id})
  SET a.account_type=r.account_type, a.status=r.status, a.opened_date=date(r.opened_date),
      a.simulated_balance_brl=toFloat(r.simulated_balance_brl), a.split=r.split
  WITH a, r MATCH (b:Branch {branch_id: r.branch_id}) MERGE (a)-[:BELONGS_TO]->(b)"""),
 ("Employee + WORKS_AT", "employees", """
  UNWIND $rows AS r MERGE (e:Employee {employee_id: r.employee_id})
  SET e.employee_name=r.employee_name, e.role=r.role, e.split=r.split
  WITH e, r MATCH (b:Branch {branch_id: r.branch_id}) MERGE (e)-[:WORKS_AT]->(b)"""),
 ("OWNS", "account_owners", """
  UNWIND $rows AS r
  MATCH (c:Customer {customer_id: r.customer_id}), (a:Account {account_id: r.account_id})
  MERGE (c)-[o:OWNS]->(a) SET o.ownership_type=r.ownership_type"""),
 ("Card + HAS_CARD + LINKED_TO", "cards", """
  UNWIND $rows AS r MERGE (k:Card {card_id: r.card_id})
  SET k.brand=r.brand, k.card_type=r.card_type, k.credit_limit_brl=toFloat(r.credit_limit_brl),
      k.status=r.status, k.split=r.split
  WITH k, r MATCH (c:Customer {customer_id: r.customer_id}), (a:Account {account_id: r.account_id})
  MERGE (c)-[:HAS_CARD]->(k) MERGE (k)-[:LINKED_TO]->(a)"""),
 ("Loan + HAS_LOAN + ON_ACCOUNT", "loans", """
  UNWIND $rows AS r MERGE (l:Loan {loan_id: r.loan_id})
  SET l.principal_brl=toFloat(r.principal_brl), l.annual_interest_rate_pct=toFloat(r.annual_interest_rate_pct),
      l.installments_total=toInteger(r.installments_total), l.installments_paid=toInteger(r.installments_paid),
      l.status=r.status, l.start_date=date(r.start_date), l.split=r.split
  WITH l, r MATCH (c:Customer {customer_id: r.customer_id}), (a:Account {account_id: r.account_id})
  MERGE (c)-[:HAS_LOAN]->(l) MERGE (l)-[:ON_ACCOUNT]->(a)"""),
 ("Transaction + SENT + PAID_TO", "transactions", """
  UNWIND $rows AS r MERGE (t:Transaction {transaction_id: r.transaction_id})
  SET t.amount_brl=toFloat(r.amount_brl), t.transaction_type=r.transaction_type,
      t.timestamp=datetime(r.transaction_date+'T'+r.transaction_time), t.date=date(r.transaction_date),
      t.status=r.status, t.channel=r.channel, t.flagged=(r.flagged='True'), t.scenario=r.scenario, t.split=r.split
  WITH t, r MATCH (a:Account {account_id: r.account_id}), (m:Merchant {merchant_id: r.merchant_id})
  MERGE (a)-[:SENT]->(t) MERGE (t)-[:PAID_TO]->(m)"""),
 ("Alert + RAISED_ON", "alerts", """
  UNWIND $rows AS r MERGE (al:Alert {alert_id: r.alert_id})
  SET al.alert_type=r.alert_type, al.severity=r.severity, al.alert_date=date(r.alert_date),
      al.status=r.status, al.note=r.note
  WITH al, r MATCH (t:Transaction {transaction_id: r.transaction_id}) MERGE (al)-[:RAISED_ON]->(t)"""),
 ("Complaint + FILED (+ ABOUT)", "complaints", """
  UNWIND $rows AS r MERGE (cp:Complaint {complaint_id: r.complaint_id})
  SET cp.category=r.category, cp.description=r.description, cp.status=r.status,
      cp.created_date=date(r.created_date), cp.split=r.split
  WITH cp, r MATCH (c:Customer {customer_id: r.customer_id}) MERGE (c)-[:FILED]->(cp)
  WITH cp, r WHERE r.transaction_id IS NOT NULL
  MATCH (t:Transaction {transaction_id: r.transaction_id}) MERGE (cp)-[:ABOUT]->(t)"""),
 ("Document", "documents", """
  UNWIND $rows AS r MERGE (d:Document {document_id: r.document_id})
  SET d.title=r.title, d.document_type=r.document_type, d.version=toInteger(r.version),
      d.published_date=date(r.published_date), d.section=r.section, d.page=toInteger(r.page),
      d.text=r.text, d.split=r.split"""),
 ("BankingRule + DESCRIBES", "banking_rules", """
  UNWIND $rows AS r MERGE (br:BankingRule {rule_id: r.rule_id})
  SET br.rule_name=r.rule_name, br.description=r.description, br.applies_to=r.applies_to,
      br.severity=r.severity, br.is_active=(r.is_active='True'), br.split=r.split
  WITH br, r MATCH (d:Document {document_id: r.document_id}) MERGE (d)-[:DESCRIBES]->(br)"""),
]

# Heuristica (decisao de modelagem): todo Loan segue as regras de "Empréstimo Pessoal".
EXTRA = [("Loan FOLLOWS BankingRule (heuristica por rule_name)", """
  MATCH (br:BankingRule {rule_name:'Empréstimo Pessoal', is_active:true}), (l:Loan)
  MERGE (l)-[:FOLLOWS]->(br)""")]

# Contagem esperada de nos/relacionamentos, calculada a partir dos CSVs.
def expected(d):
    return {
      "Customer": len(d["customers"]), "Account": len(d["accounts"]), "Transaction": len(d["transactions"]),
      "Loan": len(d["loans"]), "Card": len(d["cards"]), "Merchant": len(d["merchants"]),
      "Branch": len(d["branches"]), "Employee": len(d["employees"]), "Alert": len(d["alerts"]),
      "Complaint": len(d["complaints"]), "Document": len(d["documents"]), "BankingRule": len(d["banking_rules"]),
      "rel:OWNS": len(d["account_owners"]), "rel:SENT": len(d["transactions"]),
      "rel:PAID_TO": len(d["transactions"]), "rel:HAS_CARD": len(d["cards"]), "rel:LINKED_TO": len(d["cards"]),
      "rel:HAS_LOAN": len(d["loans"]), "rel:ON_ACCOUNT": len(d["loans"]), "rel:BELONGS_TO": len(d["accounts"]),
      "rel:WORKS_AT": len(d["employees"]), "rel:RAISED_ON": len(d["alerts"]), "rel:FILED": len(d["complaints"]),
      "rel:ABOUT": int((d["complaints"]["transaction_id"] != "").sum()), "rel:DESCRIBES": len(d["banking_rules"]),
    }

def split_statements(text):
    text = re.sub(r"//.*", "", text)
    return [s.strip() for s in text.split(";") if s.strip()]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--batch", type=int, default=1000)
    ap.add_argument("--wipe", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    names = [s[1] for s in STEPS]
    d = {n: read(a.data, n) for n in names}
    exp = expected(d)
    if a.dry_run:
        print("DRY-RUN: CSVs lidos. Contagens esperadas no grafo:")
        for k, v in exp.items(): print(f"  {k:16} {v}")
        return

    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    drv.verify_connectivity()
    with drv.session() as s:
        if a.wipe:
            s.run("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS")
        for st in split_statements((Path(__file__).parent / "schema.cypher").read_text(encoding="utf-8")):
            s.run(st)
        print("schema ok")
        for label, csv, q in STEPS:
            data = rows(d[csv])
            for i in range(0, len(data), a.batch):
                s.run(q, rows=data[i:i + a.batch]).consume()
            print(f"{label:38} {len(data):>6} linhas")
        for label, q in EXTRA:
            s.run(q).consume(); print(label)

        # validacao: esperado (CSV) x obtido (grafo)
        ok = True
        print("\nVALIDACAO")
        for k, v in exp.items():
            if k.startswith("rel:"):
                got = s.run(f"MATCH ()-[r:{k[4:]}]->() RETURN count(r) AS n").single()["n"]
            else:
                got = s.run(f"MATCH (n:{k}) RETURN count(n) AS n").single()["n"]
            flag = "OK " if got == v else "ERRO"; ok &= got == v
            print(f"  {flag} {k:16} esperado={v:<6} obtido={got}")
        orphans = s.run("MATCH (a:Account) WHERE NOT ()-[:OWNS]->(a) RETURN count(a) AS n").single()["n"]
        print(f"  {'OK ' if orphans == 0 else 'ERRO'} contas sem dono: {orphans}")
        ok &= orphans == 0
    drv.close()
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
