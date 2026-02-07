# Skill Data Developer Guide

**Target Audience:** Data Engineers / Developers defining new skills for Jarvis.
**Purpose:** This document provides a precise technical explanation of how to edit CSV files in the `CIM-skill_rag` folder to teach the system new tricks without touching the server code.

---

## 1. How It Works: The System's "Brain"

The system is **Data-Driven**. It does not decide how to solve a task itself but looks it up in your CSV tables.

The flow for a user request (e.g., *"Send an email to Boss"*):

1. **Recognition (`intent_category_map.csv`):** The system searches for a RegEx pattern matching *"email"*. -> Finds Template ID `TMPL-EMAIL-01`.
2. **Structure (`skill_templates.csv`):** It loads the Python code skeleton for `TMPL-EMAIL-01`. This ensures safe libraries are used.
3. **Implementation (`meta_prompts.csv`):** A "CODER" Agent fills this skeleton with concrete details (recipient, subject) from the user request.
4. **Validation (`security_policies.csv`):** The final code is checked against security rules (e.g., "Port 25 prohibited").

---

## 2. The CSV Files (Specs)

### A. `intent_category_map.csv` (The "Ear")

Here you teach the system to understand user language.

| Column | Description | Example |
|---|---|---|
| `intent_pattern` | **RegEx** the user text must match. Case-insensitive. | `(email\|mail\|send.*message)` |
| `category` | Broad category (for logs/stats). | `communication` |
| `confidence` | Match confidence (0.0 - 1.0). Usually `0.9`. | `0.95` |
| `template_ref` | **IMPORTANT:** The ID of the template to load. | `TMPL-EMAIL-01` |
| `semantic_description` | Help for the AI if RegEx fails (Fallback). | "Send an email via SMTP." |

### B. `skill_templates.csv` (The "Model")

Here you define the technical implementation. This is **not verified** code, but a template the AI fills in.

| Column | Description | Example |
|---|---|---|
| `template_id` | Unique ID (referenced in Map). | `TMPL-EMAIL-01` |
| `intent_keywords` | Simple keywords as fallback. | `email\|smtp` |
| `code_template` | **The Python Code.** Must contain a `run(**kwargs)` function. | `def run(**kwargs): ...` (see below) |
| `permissions_required` | Required skill permissions (informational). | `internet` |

### C. `security_policies.csv` (The "Bouncer")

Rules for what the code is NOT allowed to do.

| Column | Description | Example |
|---|---|---|
| `rule_description` | Name of the rule. | `No Root` |
| `check_function` | Technical condition (Python Expression). | `uid != 0` or `'os.system' not in code` |
| `severity` | `CRITICAL` (Block), `HIGH` (Warning). | `CRITICAL` |

---

## 3. Complex Examples (Templates)

Here are "Best Practice" templates for complex scenarios. **Important:** Templates must be robust. Catch errors (`try/except`) and return Dictionaries.

### Example 1: n8n Webhook Trigger (`automation`)

*Usage: When the user wants to trigger external processes.*

**Code Template:**

```python
def run(**kwargs):
    """Trigger an n8n webhook."""
    import httpx
    
    # 1. Extract parameter safely
    # The AI will extract 'webhook_id' from user text
    webhook_id = kwargs.get('webhook_id', 'my-default-hook') 
    payload = kwargs.get('data', {})
    
    # 2. Hardcoded Base URL for security (User cannot change domain)
    n8n_base = "http://n8n:5678/webhook/"
    
    try:
        # 3. Execute Request
        url = f"{n8n_base}{webhook_id}"
        resp = httpx.post(url, json=payload, timeout=5.0)
        
        # 4. Return structured result
        return {
            "success": resp.status_code == 200,
            "status": resp.status_code,
            "response": resp.text
        }
    except Exception as e:
        return {"error": str(e)}
```

### Example 2: Gmail Sending (`communication`)

*Usage: Sending emails. Note: Observe Port Policies!*

**Code Template:**

```python
def run(**kwargs):
    """Send email via SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    
    # 1. Credentials (should ideally come from ENV, not hardcoded)
    # Placeholder that AI should NOT overwrite
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587 # Port 465/587 allowed, 25 often blocked
    
    sender = kwargs.get('sender_email')
    password = kwargs.get('password') # Or os.getenv('MAIL_PW')
    recipient = kwargs.get('to')
    subject = kwargs.get('subject', 'No Subject')
    body = kwargs.get('body', '')
    
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient
    
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return {"success": True, "recipient": recipient}
    except Exception as e:
        return {"error": f"SMTP Error: {str(e)}"}
```

### Example 3: SQL Database Query (`database`)

*Usage: Data retrieval. IMPORTANT: Enforce Read-Only if possible.*

**Code Template:**

```python
def run(**kwargs):
    """Execute SQL query safely."""
    # NOTE: Only standard libs allowed. For Postgres/MySQL, 'psycopg2' must be whitelisted.
    # Example with SQLite or generic structure.
    import sqlite3 
    
    query = kwargs.get('query', '')
    db_path = "/data/db/chinook.db" # Fixed path!
    
    # Security Check: No DROP/DELETE allowed
    if any(x in query.lower() for x in ['drop', 'delete', 'truncate']):
        return {"error": "Destructive queries not allowed via Skills."}
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        return {"count": len(rows), "data": rows[:10]} # Limit Return Size
    except Exception as e:
        return {"error": str(e)}
```

---

## 4. Limitations & Rules

What the Data Developer must observe:

1. **No GUI:** Skills run in the background. There is no `print()` output to the user. Results must **always** be returned as `return {dict}`.
2. **Imports:** Only libraries installed in the Docker container are available (`httpx`, `beautifulsoup4`, Standard Libs). If you want to use `pandas` in a template, it must be in the container.
3. **Time Limit:** Skills often have short execution times (e.g., 30-60s). No long-running jobs.
4. **CSV Escaping:** If your Python code contains commas `,` or quotes `"`, you must escape the CSV field correctly (wrap in double quotes `"..."`).
    * *Wrong:* `TMPL-01, def run(): print("Hi"), ...`
    * *Right:* `TMPL-01,"def run(): print(""Hi"")",...`
5. **Environment Variables:** NEVER write real passwords in `skill_templates.csv`! Use `os.getenv('MY_SECRET')` in Python code and set the Env-Var in the container.

## 5. Developer Workflow

1. New row in `intent_category_map.csv`: "What should it listen for?"
2. New row in `skill_templates.csv`: "What should it do (Code)?"
3. Save file.
4. Reload server: `docker restart jarvis-skill-server`.
5. Test: "Jarvis, [Say Keyword]..."
