import os
import re
import json
import requests
from supabase import create_client
import google.generativeai as genai
from datetime import datetime

# ==============================
# ENVIRONMENT VARIABLES
# ==============================

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_USERNAME = os.environ["ODOO_USERNAME"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# ==============================
# INIT CLIENTS
# ==============================

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ==============================
# STEP 1 - REGEX EXTRACT
# ==============================

def extract_by_regex(content):
    content = content.upper()

    patterns = [
        r'HD\s*0*(\d+)',
        r'HOA\s*DON\s*0*(\d+)',
        r'\bS(\d{5,})\b',
        r'\b(\d{4,6})\b'
    ]

    results = set()
    for p in patterns:
        matches = re.findall(p, content)
        for m in matches:
            results.add(m)

    return list(results)

# ==============================
# STEP 2 - GEMINI FALLBACK
# ==============================

def extract_by_gemini(content):
    prompt = f"""
    Extract invoice numbers or sale order numbers from this bank transfer content.
    Return JSON only:
    {{
        "numbers": ["..."]
    }}
    Text: {content}
    """

    response = model.generate_content(prompt)

    try:
        data = json.loads(response.text)
        return data.get("numbers", [])
    except:
        return []

# ==============================
# STEP 3 - CONNECT ODOO
# ==============================

def odoo_login():
    import xmlrpc.client

    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models

def find_sale_orders(candidates):
    uid, models = odoo_login()

    domain = [
        '|',
        ('e_invoicenumber', 'in', candidates),
        ('name', 'in', ['S'+c for c in candidates])
    ]

    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        'sale.order',
        'search_read',
        [domain],
        {'fields': ['name', 'amount_total', 'e_invoicenumber']}
    )

    return orders

# ==============================
# STEP 4 - MATCH BY AMOUNT
# ==============================

def match_by_amount(orders, amount):
    matched = []

    for o in orders:
        if abs(float(o["amount_total"]) - float(amount)) < 1:
            matched.append(o)

    return matched

# ==============================
# STEP 5 - LOG TO SUPABASE
# ==============================

def log_payment(data):
    supabase.table("payment_logs").insert(data).execute()

# ==============================
# STEP 6 - SEND SLACK
# ==============================

def send_slack(message):
    requests.post(SLACK_WEBHOOK, json={"text": message})

# ==============================
# MAIN HANDLER
# ==============================

def handler(request):

    if request.method != "POST":
        return {"statusCode": 405, "body": "Method Not Allowed"}

    try:
        payload = request.json()
        content = payload.get("content", "")
        amount = payload.get("amount_in", 0)
        sepay_id = payload.get("id", "")

        # 1. Regex extract
        candidates = extract_by_regex(content)

        # 2. If empty → Gemini
        if not candidates:
            candidates = extract_by_gemini(content)

        # 3. Query Odoo
        orders = find_sale_orders(candidates)

        # 4. Match amount
        matched = match_by_amount(orders, amount)

        if len(matched) == 1:
            status = "matched"
            send_slack(f"✅ Payment matched: {matched[0]['name']} - {amount}")

        elif len(matched) > 1:
            status = "multiple"
            send_slack(f"⚠ Multiple matches for {amount}: {matched}")

        elif orders:
            status = "amount_mismatch"
            send_slack(f"❌ Amount mismatch. Candidates found but amount not match.")

        else:
            status = "not_found"
            send_slack(f"❌ No sale order found for content: {content}")

        # 5. Log to Supabase
        log_payment({
            "sepay_id": sepay_id,
            "content": content,
            "amount": amount,
            "extracted_candidates": candidates,
            "matched_sale_orders": matched,
            "match_status": status,
            "error_message": None,
            "raw_payload": payload
        })

        return {"statusCode": 200, "body": "OK"}

    except Exception as e:

        log_payment({
            "sepay_id": "",
            "content": "",
            "amount": 0,
            "extracted_candidates": [],
            "matched_sale_orders": [],
            "match_status": "error",
            "error_message": str(e),
            "raw_payload": {}
        })

        return {"statusCode": 500, "body": str(e)}
