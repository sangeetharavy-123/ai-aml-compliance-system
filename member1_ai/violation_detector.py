import sys
sys.path.append('/home/sangeetharavy/compliance-project/member2_pipeline')

import vertexai
import subprocess
import requests
import uuid
import time
from datetime import datetime
from vertexai.generative_models import GenerativeModel

# ── CONFIG ──────────────────────────────────────────
PROJECT_ID = "gdg-488108"   # single source of truth
LOCATION   = "us-central1"
# ────────────────────────────────────────────────────

vertexai.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel("gemini-2.0-flash-lite")

# ── TOKEN ────────────────────────────────────────────
_token_cache = {"value": None, "expires": 0}

def get_token():
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires"]:
        return _token_cache["value"]
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, timeout=10
    )
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("gcloud token is empty — run: gcloud auth login")
    _token_cache["value"]   = token
    _token_cache["expires"] = now + 55 * 60
    print("[TOKEN] Refreshed")
    return token

# ── BIGQUERY HELPERS ─────────────────────────────────
def run_bq_query(query):
    """SELECT queries — uses the fast /queries endpoint."""
    token = get_token()
    url   = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/queries"
    hdrs  = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body  = {"query": query, "useLegacySql": False, "location": "US", "timeoutMs": 30000}
    resp  = requests.post(url, headers=hdrs, json=body, timeout=35)
    return resp.json()

def run_bq_job(query):
    """INSERT / UPDATE / DELETE — uses the Jobs API (required for DML)."""
    token = get_token()
    url   = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/jobs"
    hdrs  = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body  = {"configuration": {"query": {"query": query, "useLegacySql": False, "location": "US"}}}

    resp  = requests.post(url, headers=hdrs, json=body, timeout=30)
    job   = resp.json()

    if "error" in job:
        print(f"[JOB ERROR] Could not start job: {job['error']}")
        return False

    job_id = job.get("jobReference", {}).get("jobId", "")
    print(f"[JOB] Started: {job_id}")

    for _ in range(40):          # wait up to 40 s
        time.sleep(1)
        st    = requests.get(
            f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/jobs/{job_id}",
            headers=hdrs, timeout=10
        ).json()
        state = st.get("status", {}).get("state", "")
        if state == "DONE":
            err = st.get("status", {}).get("errorResult")
            if err:
                print(f"[JOB FAILED] {err}")
                return False
            return True

    print("[JOB] Timeout — job took too long")
    return False

def sanitize(text, max_len=400):
    """Escape strings so they are safe inside BigQuery SQL literals."""
    if not text:
        return ""
    text = str(text)
    text = text.replace("\\", "")          # remove backslashes
    text = text.replace("\n", " ")         # newlines → space
    text = text.replace("\r", " ")
    text = text.replace("\t", " ")
    text = text.replace("'", "\\'")        # escape single quotes
    return text[:max_len]

# ── STORE VIOLATION (replaces missing store_violation module) ────
def store_violation(transaction_id, rule_id, explanation, severity, remediation,
                    status="PENDING_REVIEW"):
    """Insert one violation row directly into BigQuery."""
    vid      = "VIO-" + str(uuid.uuid4()).upper()[:8]
    detected = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    query = f"""
        INSERT INTO `{PROJECT_ID}.aml_dataset.violations`
          (violation_id, transaction_id, rule_id, explanation,
           severity, remediation, status, detected_at)
        VALUES (
          '{sanitize(vid)}',
          '{sanitize(transaction_id, 200)}',
          '{sanitize(rule_id, 100)}',
          '{sanitize(explanation, 400)}',
          '{severity}',
          '{sanitize(remediation, 300)}',
          '{status}',
          TIMESTAMP('{detected}')
        )
    """
    ok = run_bq_job(query)
    if ok:
        print(f"  ✅  Stored violation {vid} | {severity}")
    else:
        print(f"  ❌  Failed to store violation for txn {transaction_id}")
    return ok

# ── FETCH TRANSACTIONS ───────────────────────────────
def get_transactions():
    print("[BQ] Fetching transactions over $10,000 ...")
    result = run_bq_query(f"""
        SELECT Timestamp, Account, `From Bank`, `To Bank`,
               `Amount Paid`, `Payment Currency`, `Is Laundering`
        FROM `{PROJECT_ID}.aml_dataset.transactions`
        WHERE CAST(`Amount Paid` AS FLOAT64) > 10000
        LIMIT 10
    """)

    if "error" in result:
        print(f"[BQ ERROR] {result['error']}")
        return []

    if "rows" not in result:
        print("[BQ] No rows returned — check your dataset/table name.")
        return []

    fields = [f["name"] for f in result["schema"]["fields"]]
    rows   = [{fields[i]: row["f"][i]["v"] for i in range(len(fields))}
              for row in result["rows"]]
    print(f"[BQ] Found {len(rows)} transactions\n")
    return rows

# ── MAIN ─────────────────────────────────────────────
def main():
    print("\n" + "="*52)
    print("   AML VIOLATION DETECTOR")
    print(f"   Project : {PROJECT_ID}")
    print("="*52 + "\n")

    rows = get_transactions()
    if not rows:
        print("No transactions to analyse. Exiting.")
        return

    saved = 0
    for idx, txn in enumerate(rows, start=1):
        amount      = float(txn.get("Amount Paid", 0) or 0)
        account     = txn.get("Account", "N/A")
        bank        = txn.get("From Bank", "N/A")
        currency    = txn.get("Payment Currency", "USD")
        is_launder  = txn.get("Is Laundering", "0")
        severity    = "HIGH" if amount > 50000 else "MEDIUM" if amount > 20000 else "LOW"

        print(f"[{idx}/{len(rows)}] Account={account}  Amount={amount} {currency}  → {severity}")

        # Ask Gemini why this transaction is suspicious
        prompt = (
            f"You are an AML compliance officer. "
            f"Explain in exactly 2 sentences why this transaction is suspicious:\n"
            f"  Account: {account}\n"
            f"  Bank: {bank}\n"
            f"  Amount: {amount} {currency}\n"
            f"  Laundering Flag: {is_launder}"
        )
        try:
            explanation = model.generate_content(prompt).text.strip()
        except Exception as e:
            explanation = f"Transaction of {amount} {currency} from {bank} flagged for AML review."
            print(f"  [Gemini fallback] {e}")

        ok = store_violation(
            transaction_id = str(account),
            rule_id        = "RULE-001",
            explanation    = explanation,
            severity       = severity,
            remediation    = "File SAR within 30 days per FinCEN guidelines",
        )
        if ok:
            saved += 1

    print(f"\n{'='*52}")
    print(f"  Done! {saved}/{len(rows)} violations saved to BigQuery.")
    print(f"  Open the dashboard to review them.")
    print(f"{'='*52}\n")

if __name__ == "__main__":
    main()