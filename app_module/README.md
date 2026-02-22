# 🛡️ AML Compliance Agent

An AI-powered Anti-Money Laundering (AML) compliance dashboard built 
with Flask, Google BigQuery, and Gemini AI on Google Cloud Platform.

## 📋 Project Overview

This system automatically detects suspicious financial transactions,
generates AI-powered explanations, and helps compliance officers
review and act on violations — all from a single dashboard.

## 🚀 Features

- 🔍 Scan transactions over $10,000 for AML violations
- 🤖 AI-powered explanations using Gemini 2.0 Flash
- 📄 Upload compliance policy PDFs for rule extraction
- ✅ Review, confirm, or dismiss violations
- 📧 Automatic email notifications for scan results and decisions
- 📋 Full audit log tracking all officer decisions
- 🌙 Dark/Light mode dashboard UI

## 🗂️ Project Structure
```
compliance-project/
├── app.py                  # Main Flask server + API routes
├── aml_dashboard.html      # Frontend dashboard UI
├── violation_detector.py   # Batch transaction scanner
├── chatbot.py              # Standalone CLI compliance chatbot
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
└── README.md               # Project documentation
```

## ⚙️ Prerequisites

- Python 3.8+
- Google Cloud account with billing enabled
- Google Cloud project with these APIs enabled:
  - BigQuery API
  - Vertex AI API
  - Firestore API
- Gmail account with App Password enabled
- gcloud CLI installed

## 🛠️ Setup Instructions

### 1. Clone the repository
```
git clone <your-repo-url>
cd compliance-project
```

### 2. Install dependencies
```
pip install -r requirements.txt
```

### 3. Configure environment variables
```
cp .env.example .env
```
Fill in your values in .env

### 4. Authenticate with Google Cloud
```
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### 5. Configure email in app.py
```
EMAIL_SENDER    = "your-email@gmail.com"
EMAIL_PASSWORD  = "your-16-char-app-password"
EMAIL_RECIPIENT = "recipient@gmail.com"
```
Generate App Password at:
https://myaccount.google.com/apppasswords

### 6. Set up BigQuery dataset
Make sure these tables exist in BigQuery:
- aml_dataset.transactions
- aml_dataset.violations

### 7. Run the app
```
python app.py
```

### 8. Open the dashboard
```
http://localhost:8080
```

## 📊 BigQuery Table Schema

### transactions table
| Column | Type |
|--------|------|
| Account | STRING |
| From Bank | STRING |
| To Bank | STRING |
| Amount Paid | FLOAT |
| Payment Currency | STRING |
| Is Laundering | STRING |
| Timestamp | TIMESTAMP |

### violations table
| Column | Type |
|--------|------|
| violation_id | STRING |
| transaction_id | STRING |
| rule_id | STRING |
| explanation | STRING |
| severity | STRING |
| remediation | STRING |
| status | STRING |
| detected_at | TIMESTAMP |

## 🔄 How It Works

1. Transactions over $10,000 are fetched from BigQuery
2. Each transaction is analyzed by Gemini AI
3. Violations are saved with severity: HIGH / MEDIUM / LOW
4. Compliance officers review violations on the dashboard
5. Decisions are logged to Firestore audit trail
6. Email reports are sent automatically

## 🛡️ Severity Levels

| Level | Amount |
|-------|--------|
| 🔴 HIGH | Over $50,000 |
| 🟡 MEDIUM | $20,000 - $50,000 |
| 🟢 LOW | $10,000 - $20,000 |



## ⚠️ Important Notes

- Never commit real credentials to GitHub
- Use .env file for all sensitive values
- Gmail App Password must be 16 characters with no spaces
- Make sure gcloud auth is active before running

## 📄 License

MIT License
