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

def save_review_decision(violation_id, officer_decision, officer_id, notes=""):
    """
    Save compliance officer decision to Firestore
    Called when officer clicks Confirm / Dismiss / Escalate
    """
    token = get_token()
    review_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Save to Firestore
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/violation_reviews/{review_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {
        "fields": {
            "review_id": {"stringValue": review_id},
            "violation_id": {"stringValue": violation_id},
            "officer_decision": {"stringValue": officer_decision},
            "officer_id": {"stringValue": officer_id},
            "notes": {"stringValue": notes},
            "reviewed_at": {"stringValue": timestamp}
        }
    }

    response = requests.patch(url, headers=headers, json=body)

    if response.status_code == 200:
        print(f"Decision saved: {officer_decision} for violation {violation_id}")

        # Also update violation status in BigQuery
        update_violation_status(violation_id, officer_decision)
        return review_id
    else:
        print(f"Error saving decision: {response.json()}")
        return None

def update_violation_status(violation_id, new_status):
    """Update violation status in BigQuery after officer review"""
    token = get_token()
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/queries"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {
        "query": f"""
            UPDATE `{PROJECT_ID}.aml_dataset.violations`
            SET status = '{new_status}'
            WHERE violation_id = '{violation_id}'
        """,
        "useLegacySql": False,
        "location": "US"
    }
    response = requests.post(url, headers=headers, json=body)
    print(f"Violation {violation_id} status updated to: {new_status}")

def get_all_violations():
    """Get all violations for Member 3 dashboard"""
    token = get_token()
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/queries"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    body = {
        "query": f"""
            SELECT * FROM `{PROJECT_ID}.aml_dataset.violations`
            ORDER BY detected_at DESC
            LIMIT 100
        """,
        "useLegacySql": False,
        "location": "US"
    }
    response = requests.post(url, headers=headers, json=body)
    data = response.json()

    violations = []
    if 'rows' in data:
        fields = [f['name'] for f in data['schema']['fields']]
        for row in data['rows']:
            violation = {}
            for i, field in enumerate(fields):
                violation[field] = row['f'][i]['v']
            violations.append(violation)
    return violations

def get_all_reviews():
    """Get all review decisions for audit report"""
    token = get_token()
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/violation_reviews"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    data = response.json()

    reviews = []
    if 'documents' in data:
        for doc in data['documents']:
            review = {}
            for key, val in doc['fields'].items():
                review[key] = list(val.values())[0]
            reviews.append(review)
    return reviews

# Test the handler
if __name__ == "__main__":
    print("Testing Firestore handler...")
    test_id = save_review_decision(
        violation_id="TEST-001",
        officer_decision="CONFIRMED",
        officer_id="sangeetharavy@gmail.com",
        notes="Test review decision"
    )
    if test_id:
        print(f"Firestore working — Review ID: {test_id}")
    else:
        print("Firestore test failed")
