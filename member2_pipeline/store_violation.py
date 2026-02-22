
import subprocess
import requests
import json
import uuid
from datetime import datetime

PROJECT_ID = "gdg-488108"

def get_token():
    result = subprocess.run(
        ['gcloud', 'auth', 'print-access-token'],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def store_violation(transaction_id, rule_id, explanation, severity, remediation):
    """
    Store a detected violation in BigQuery
    Member 1 calls this function when violation is found
    """
    token = get_token()
    violation_id = f"VIO-{str(uuid.uuid4())[:8].upper()}"
    detected_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/tabledata/insertAll"

    # Use insertAll for streaming insert
    insert_url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/datasets/aml_dataset/tables/violations/insertAll"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "rows": [{
            "insertId": violation_id,
            "json": {
                "violation_id": violation_id,
                "transaction_id": transaction_id,
                "rule_id": rule_id,
                "explanation": explanation,
                "severity": severity,
                "remediation": remediation,
                "status": "PENDING_REVIEW",
                "detected_at": detected_at
            }
        }]
    }

    response = requests.post(insert_url, headers=headers, json=body)

    if response.status_code == 200:
        print(f"Violation stored: {violation_id}")
        # Send Pub/Sub alert
        send_pubsub_alert(violation_id, severity, transaction_id)
        return violation_id
    else:
        print(f"Error: {response.json()}")
        return None

def send_pubsub_alert(violation_id, severity, transaction_id):
    """Send real time alert when violation is stored"""
    token = get_token()
    import base64

    message = json.dumps({
        "violation_id": violation_id,
        "severity": severity,
        "transaction_id": transaction_id,
        "alert_type": "NEW_VIOLATION",
        "timestamp": datetime.utcnow().isoformat()
    })

    url = f"https://pubsub.googleapis.com/v1/projects/{PROJECT_ID}/topics/violation-alerts:publish"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {
        "messages": [{
            "data": base64.b64encode(message.encode()).decode()
        }]
    }

    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        print(f"Alert sent to Pub/Sub for violation: {violation_id}")
    else:
        print(f"Pub/Sub error: {response.json()}")

# Test it
if __name__ == "__main__":
    print("Testing store_violation function...")
    vid = store_violation(
        transaction_id="TXN-001234",
        rule_id="RULE-001",
        explanation="Transaction of $15,200 exceeds $10,000 AML threshold. Potential structuring attempt detected.",
        severity="HIGH",
        remediation="Freeze account immediately. File SAR within 30 days."
    )
    if vid:
        print(f"Test violation stored successfully: {vid}")
        print("Member 1 can now call store_violation() to save violations")
