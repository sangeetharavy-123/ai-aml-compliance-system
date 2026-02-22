import sys
sys.path.append('/home/sangeetharavy/compliance-project/member2_pipeline')

import subprocess, requests, uuid, smtplib, threading, time, os, base64, socket
from flask import Flask, jsonify, request, send_file
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Vertex AI SDK ──────────────────────────────────────
import vertexai
from vertexai.generative_models import GenerativeModel

vertexai.init(project="gdg-488108", location="us-central1")
gemini_model = GenerativeModel("gemini-2.0-flash-lite")

def get_server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

SERVER_IP = get_server_ip()
DASHBOARD_URL = f"http://{SERVER_IP}:8080"

app = Flask(__name__)
PROJECT_ID = "gdg-488108"

# ════════════════════════════════════════════════════════
#  ✏️  FILL IN YOUR EMAIL DETAILS HERE  (3 lines to edit)
# ════════════════════════════════════════════════════════
EMAIL_SENDER    = "your-email@gmail.com"    # 👈 your Gmail
EMAIL_PASSWORD  = "your-app-password-here"          # 👈 Gmail App Password (16 chars, no spaces)
EMAIL_RECIPIENT = "your-email@gmail.com"    # 👈 who receives reports
# ════════════════════════════════════════════════════════

_token_cache = {"value": None, "expires": 0}

def get_token():
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires"]:
        return _token_cache["value"]
    result = subprocess.run(["gcloud","auth","print-access-token"],
                            capture_output=True, text=True, timeout=10)
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("gcloud token empty — run: gcloud auth login")
    _token_cache["value"]   = token
    _token_cache["expires"] = now + 55*60
    print("[TOKEN] Refreshed")
    return token

_cache={}; _cache_ts={}; CACHE_TTL=20

def cache_get(k):
    return _cache.get(k) if (time.time()-_cache_ts.get(k,0))<CACHE_TTL else None

def cache_set(k,v):
    _cache[k]=v; _cache_ts[k]=time.time()

def cache_clear():
    _cache.clear(); _cache_ts.clear()
    print("[CACHE] Cleared")

def run_bq(query):
    token = get_token()
    url   = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/queries"
    hdrs  = {"Authorization":f"Bearer {token}","Content-Type":"application/json"}
    body  = {"query":query,"useLegacySql":False,"location":"US","timeoutMs":30000}
    resp  = requests.post(url,headers=hdrs,json=body,timeout=35)
    result = resp.json()
    if "error" in result:
        print(f"[BQ ERROR] {result['error']}")
    return result

def run_bq_job(query):
    token = get_token()
    url   = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/jobs"
    hdrs  = {"Authorization":f"Bearer {token}","Content-Type":"application/json"}
    body  = {"configuration":{"query":{"query":query,"useLegacySql":False,"location":"US"}}}
    resp  = requests.post(url,headers=hdrs,json=body,timeout=30)
    job   = resp.json()
    if "error" in job:
        print(f"[JOB ERROR] {job['error']}")
        return False
    job_id = job.get("jobReference",{}).get("jobId","")
    print(f"[JOB] Started: {job_id}")
    for _ in range(40):
        time.sleep(1)
        st = requests.get(
            f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/jobs/{job_id}",
            headers=hdrs, timeout=10).json()
        state = st.get("status",{}).get("state","")
        if state == "DONE":
            err = st.get("status",{}).get("errorResult")
            if err:
                print(f"[JOB FAILED] {err}")
                return False
            print(f"[JOB] Done OK: {job_id}")
            return True
    print("[JOB] Timeout")
    return False

def sanitize(text, max_len=400):
    if not text: return ""
    text = str(text)
    text = text.replace("\n"," ").replace("\r"," ").replace("\t"," ")
    text = text.replace("\\","").replace("'","\\'")
    return text[:max_len]

# ── Gemini via Vertex AI SDK (replaces raw REST) ───────
def ask_gemini(prompt):
    """Call Gemini using the Vertex AI SDK — faster and more reliable."""
    try:
        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"[GEMINI ERROR] {e}")
        return "AI explanation unavailable."

# ── AML-specific chatbot call with system prompt ───────
AML_SYSTEM_PROMPT = """You are an AML Compliance AI Agent.
You ONLY answer questions about AML (Anti-Money Laundering), compliance,
transactions, violations, audit reports, SAR filing, FinCEN guidelines,
and financial regulations.
If a question is not related to these topics, politely say you can only
help with AML and financial compliance questions.
Keep answers clear, concise, and professional.
"""

def ask_gemini_chat(user_question):
    """Dedicated chatbot call with AML system prompt."""
    try:
        full_prompt = AML_SYSTEM_PROMPT + "\nUser Question: " + user_question
        response = gemini_model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        print(f"[CHAT ERROR] {e}")
        return "Sorry, I could not process your question. Please try again."

def send_email(subject, plain_body, recipient=None):
    """Send HTML email in background thread with clear error messages."""
    def _worker():
        try:
            to  = recipient or EMAIL_RECIPIENT
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = EMAIL_SENDER
            msg["To"]      = to
            html = f"""
<html><body style="margin:0;padding:32px;background:#f0f4fc;font-family:Arial,sans-serif">
<div style="max-width:600px;margin:auto;background:#fff;border-radius:16px;overflow:hidden;
     box-shadow:0 4px 24px rgba(0,0,0,.1);border:1px solid #dce4f5">
  <div style="padding:28px 32px;background:linear-gradient(135deg,#1e2840,#2a3a5c)">
    <div style="font-size:36px;margin-bottom:8px">🛡️</div>
    <h2 style="color:#fff;margin:0;font-size:22px;font-weight:900">AML Compliance Agent</h2>
    <p style="color:#a8b8d8;margin:6px 0 0;font-size:13px">Project: gdg-488108</p>
  </div>
  <div style="padding:32px">
    <h3 style="color:#1a2340;margin:0 0 20px">{subject}</h3>
    <div style="background:#f5f8ff;border-left:4px solid #4f8ef7;border-radius:4px;
         padding:20px 24px;color:#3d5280;font-size:14px;line-height:2;
         white-space:pre-line;font-family:monospace">{plain_body}</div>
    <div style="margin-top:24px;padding-top:16px;border-top:1px solid #dce4f5;text-align:center">
      <p style="color:#6a7fa8;font-size:12px;margin:0">
        AML Agent · {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} ·
        <a href="{DASHBOARD_URL}" style="color:#4f8ef7">Open Dashboard →</a>
      </p>
    </div>
  </div>
</div></body></html>"""
            msg.attach(MIMEText(plain_body,"plain"))
            msg.attach(MIMEText(html,"html"))
            with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=15) as s:
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.sendmail(EMAIL_SENDER, to, msg.as_string())
            print(f"[EMAIL OK] ✅ '{subject}' → {to}")
        except smtplib.SMTPAuthenticationError:
            print("[EMAIL FAIL] ❌ Wrong email or App Password!")
            print("   → Go to myaccount.google.com/apppasswords and create a new App Password")
            print("   → Paste it into EMAIL_PASSWORD in app.py (no spaces)")
        except Exception as e:
            print(f"[EMAIL FAIL] ❌ {e}")
    threading.Thread(target=_worker, daemon=True).start()

# ── ROUTES ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_file("aml_dashboard.html")

@app.route("/api/summary")
def api_summary():
    cached = cache_get("summary")
    if cached: return jsonify(cached)
    r = run_bq(f"""SELECT COUNT(*) AS total,
        COUNTIF(severity='HIGH') AS high, COUNTIF(severity='MEDIUM') AS medium,
        COUNTIF(severity='LOW') AS low, COUNTIF(status='PENDING_REVIEW') AS pending,
        COUNTIF(status='CONFIRMED') AS confirmed, COUNTIF(status='DISMISSED') AS dismissed
        FROM `{PROJECT_ID}.aml_dataset.violations`""")
    data = dict(total=0,high=0,medium=0,low=0,pending=0,confirmed=0,dismissed=0)
    if "rows" in r:
        v = r["rows"][0]["f"]
        for i,k in enumerate(data): data[k] = int(v[i]["v"] or 0)
    print(f"[SUMMARY] {data}")
    cache_set("summary", data)
    return jsonify(data)

@app.route("/api/violations")
def api_violations():
    cached = cache_get("violations")
    if cached: return jsonify(cached)
    r = run_bq(f"""SELECT violation_id, transaction_id, rule_id, explanation,
        severity, remediation, status, detected_at
        FROM `{PROJECT_ID}.aml_dataset.violations`
        ORDER BY detected_at DESC LIMIT 200""")
    rows = []
    if "rows" in r:
        fields = [f["name"] for f in r["schema"]["fields"]]
        for row in r["rows"]:
            rows.append({fields[i]: row["f"][i]["v"] for i in range(len(fields))})
    print(f"[VIOLATIONS] {len(rows)} rows")
    data = {"violations": rows, "total": len(rows)}
    cache_set("violations", data)
    return jsonify(data)

@app.route("/api/scan", methods=["POST"])
def api_scan():
    print("\n" + "="*50)
    print("[SCAN] Started")
    rules_text=""; rules_count=0; tmp_path=None
    content_type = request.content_type or ""

    if "application/json" in content_type:
        payload      = request.get_json(force=True, silent=True) or {}
        notify_email = payload.get("email", EMAIL_RECIPIENT)
        pdf_b64      = payload.get("pdf_base64","")
        pdf_filename = payload.get("pdf_filename","upload.pdf")
        if pdf_b64:
            tmp_path = f"/tmp/{uuid.uuid4()}_{pdf_filename}"
            try:
                with open(tmp_path,"wb") as fh:
                    fh.write(base64.b64decode(pdf_b64))
            except Exception as e:
                return jsonify({"error":f"PDF decode failed: {e}"}), 400
    else:
        notify_email = request.form.get("email", EMAIL_RECIPIENT)
        if "pdf" in request.files:
            f=request.files["pdf"]
            tmp_path=f"/tmp/{uuid.uuid4()}_{f.filename}"
            f.save(tmp_path)

    # PDF rules
    if tmp_path and os.path.exists(tmp_path):
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(tmp_path)
            raw    = " ".join(p.extract_text() or "" for p in reader.pages)
            if raw.strip():
                rules_text  = ask_gemini("Extract numbered AML compliance rules, one per line:\n\n"+raw[:4000])
                rules_count = sum(1 for l in rules_text.splitlines() if l.strip())
            else:
                rules_text = "PDF had no extractable text."
        except ImportError:
            rules_text = "PyPDF2 not installed — run: pip install PyPDF2"
        except Exception as e:
            rules_text = f"PDF error: {e}"
        finally:
            try: os.remove(tmp_path)
            except: pass
        print(f"[SCAN] {rules_count} rules extracted")

    # Transactions
    txns = run_bq(f"""
        SELECT Account, `From Bank`, `Amount Paid`, `Payment Currency`, `Is Laundering`
        FROM `{PROJECT_ID}.aml_dataset.transactions`
        WHERE CAST(`Amount Paid` AS FLOAT64) > 10000 LIMIT 10
    """)
    if "error" in txns:
        return jsonify({"error":"BigQuery failed: "+str(txns["error"])}), 500
    rows=[]
    if "rows" in txns:
        fields = [f["name"] for f in txns["schema"]["fields"]]
        rows   = [{fields[i]: row["f"][i]["v"] for i in range(len(fields))} for row in txns["rows"]]
    if not rows:
        return jsonify({"success":False,"error":"No transactions found over $10,000.","saved":0,"high_count":0})

    saved=0; high_count=0; errors=[]
    for idx, t in enumerate(rows):
        try:
            amount   = float(t.get("Amount Paid") or 0)
            account  = str(t.get("Account","N/A"))
            bank     = str(t.get("From Bank","N/A"))
            currency = str(t.get("Payment Currency","USD"))
            flag     = str(t.get("Is Laundering","0"))
            severity = "HIGH" if amount>50000 else "MEDIUM" if amount>20000 else "LOW"
            if severity=="HIGH": high_count+=1
            print(f"[SCAN] [{idx+1}/{len(rows)}] {account} ${amount} → {severity}")
            try:
                explanation = ask_gemini(
                    f"In 2 sentences explain why this is suspicious for AML.\n"
                    f"Account={account}, Bank={bank}, Amount={amount} {currency}, Flag={flag}"
                ).strip()
            except:
                explanation = f"Transaction of {amount} {currency} from {bank} flagged for AML review."

            vid = "VIO-" + str(uuid.uuid4()).upper()[:8]
            det = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            ok  = run_bq_job(f"""
                INSERT INTO `{PROJECT_ID}.aml_dataset.violations`
                  (violation_id,transaction_id,rule_id,explanation,severity,remediation,status,detected_at)
                VALUES('{vid}','{sanitize(account,200)}','RULE-AUTO-001',
                  '{sanitize(explanation,400)}','{severity}',
                  'File SAR within 30 days per FinCEN guidelines',
                  'PENDING_REVIEW',TIMESTAMP('{det}'))
            """)
            if ok: saved+=1
            else: errors.append(f"Insert failed: {account}")
        except Exception as e:
            errors.append(str(e))

    cache_clear()

    ts   = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    body = (
        f"Scan completed at {ts}\n"
        f"{'─'*42}\n"
        f"PDF Policy     : {'Processed — '+str(rules_count)+' rules' if rules_count else 'Not uploaded'}\n"
        f"Transactions   : {len(rows)} checked\n"
        f"Violations     : {saved} saved\n"
        f"  🔴 HIGH      : {high_count}\n"
        f"  🟡 MEDIUM/LOW: {saved-high_count}\n"
        f"{'─'*42}\n"
        + (f"\nExtracted Rules:\n{rules_text[:500]}\n" if rules_text else "")
        + (f"\n⚠️ ACTION REQUIRED: {high_count} HIGH risk violations need immediate review!\n" if high_count else "")
        + "\n👉 Open the AML Dashboard to review violations."
        + (f"\n\n❌ Errors:\n"+"\n".join(errors) if errors else "")
    )
    send_email(f"🛡️ AML Scan Report — {saved} violations ({high_count} HIGH)", body, notify_email)

    return jsonify({
        "success":True,"rules_count":rules_count,
        "rules_preview":rules_text[:500] if rules_text else "",
        "saved":saved,"high_count":high_count,"transactions":len(rows),
        "email_sent":True,"notified":notify_email,"errors":errors,
        "message":f"Scan complete! {saved} violations saved. Email sent to {notify_email}."
    })

@app.route("/api/review", methods=["POST"])
def api_review():
    data         = request.json or {}
    violation_id = data.get("violation_id","")
    decision     = data.get("decision","")
    officer      = data.get("officer_id", EMAIL_RECIPIENT)
    notes        = data.get("notes","")
    if decision not in ("CONFIRMED","DISMISSED"):
        return jsonify({"success":False,"error":"Invalid decision"}), 400
    try:
        from firestore_handler import save_review_decision
        save_review_decision(violation_id=violation_id, officer_decision=decision, officer_id=officer)
    except Exception as e:
        print(f"[REVIEW] Firestore skipped: {e}")
    ok = run_bq_job(
        f"UPDATE `{PROJECT_ID}.aml_dataset.violations` "
        f"SET status='{decision}' WHERE violation_id='{sanitize(violation_id,100)}'"
    )
    print(f"[REVIEW] BQ: {'✅' if ok else '❌'}")
    cache_clear()
    send_email(
        f"{'✅ Confirmed' if decision=='CONFIRMED' else '❌ Dismissed'}: Violation {violation_id[:16]}",
        f"{'─'*42}\n"
        f"Violation ID : {violation_id}\n"
        f"Decision     : {decision}\n"
        f"Officer      : {officer}\n"
        f"Notes        : {notes or 'None'}\n"
        f"Time         : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"{'─'*42}\n\nSaved to audit trail. Open Dashboard to view all records.",
        officer
    )
    return jsonify({"success":True,"violation_id":violation_id,"decision":decision})

@app.route("/api/chat", methods=["POST"])
def api_chat():
    """AML chatbot — uses dedicated system prompt for accurate, on-topic answers."""
    data = request.json or {}
    q = data.get("question","").strip()
    if not q:
        return jsonify({"answer": "Please ask a question."})
    print(f"[CHAT] Question: {q}")
    answer = ask_gemini_chat(q)
    print(f"[CHAT] Answer: {answer[:80]}...")
    return jsonify({"answer": answer})

@app.route("/api/audit")
def api_audit():
    try:
        token = get_token()
        url   = (f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}"
                 f"/databases/(default)/documents/violation_reviews")
        r     = requests.get(url, headers={"Authorization":f"Bearer {token}"}, timeout=15)
        docs  = r.json().get("documents",[])
        reviews = []
        for doc in docs:
            f = doc.get("fields",{})
            reviews.append({k: f.get(k,{}).get("stringValue","")
                for k in ["review_id","violation_id","officer_decision","officer_id","reviewed_at"]})
        return jsonify({"reviews": reviews})
    except Exception as e:
        return jsonify({"reviews":[],"error":str(e)})

@app.route("/api/test-email", methods=["POST"])
def api_test_email():
    to = (request.json or {}).get("email", EMAIL_RECIPIENT)
    send_email(
        "✅ AML Agent — Email Test Successful",
        f"Your email notifications are working!\n\n"
        f"{'─'*42}\n"
        f"Recipient : {to}\n"
        f"Sent at   : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"{'─'*42}\n\n"
        f"You will receive emails automatically when:\n"
        f"  🔍  A scan completes\n"
        f"  ⚖️   A violation is confirmed or dismissed\n"
        f"  🧪  You send a manual test like this one\n\n"
        f"Setup is complete. ✅", to
    )
    return jsonify({"success":True,"message":f"Test email sent to {to}"})

@app.route("/api/debug")
def api_debug():
    cols_r = run_bq(f"""SELECT column_name, data_type
        FROM `{PROJECT_ID}.aml_dataset.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name='violations' ORDER BY ordinal_position""")
    cols=[]
    if "rows" in cols_r:
        for row in cols_r["rows"]:
            cols.append({"col":row["f"][0]["v"],"type":row["f"][1]["v"]})
    cnt_r = run_bq(f"SELECT COUNT(*) FROM `{PROJECT_ID}.aml_dataset.violations`")
    count = int(cnt_r["rows"][0]["f"][0]["v"] or 0) if "rows" in cnt_r else 0
    txn_r = run_bq(f"SELECT COUNT(*) FROM `{PROJECT_ID}.aml_dataset.transactions` WHERE CAST(`Amount Paid` AS FLOAT64)>10000")
    txns  = int(txn_r["rows"][0]["f"][0]["v"] or 0) if "rows" in txn_r else 0
    email_ok = EMAIL_SENDER != "yourgmail@gmail.com" and EMAIL_PASSWORD != "xxxx xxxx xxxx xxxx"
    return jsonify({
        "violations_columns":cols,"violations_count":count,
        "transactions_over_10k":txns,"project":PROJECT_ID,
        "email_configured":email_ok,
        "email_sender":EMAIL_SENDER,"email_recipient":EMAIL_RECIPIENT
    })

if __name__ == "__main__":
    print("\n"+"="*52)
    print("   AML COMPLIANCE AGENT v3.2")
    print("="*52)
    if EMAIL_SENDER == "yourgmail@gmail.com":
        print("   ⚠️  WARNING: Email NOT configured!")
        print("   Open app.py and fill in EMAIL_SENDER,")
        print("   EMAIL_PASSWORD, and EMAIL_RECIPIENT")
    else:
        print(f"   ✅ Email sender    : {EMAIL_SENDER}")
        print(f"   ✅ Email recipient : {EMAIL_RECIPIENT}")
    print(f"   ✅ Gemini model    : gemini-2.0-flash-lite (Vertex AI SDK)")
    print(f"   Dashboard : {DASHBOARD_URL}")
    print(f"   Debug     : {DASHBOARD_URL}/api/debug")
    print("="*52+"\n")
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)