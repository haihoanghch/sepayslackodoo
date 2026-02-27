import os
import re
import json
import hmac
import hashlib
import xmlrpc.client
from supabase import create_client
from slack_sdk import WebClient

# ===== INIT =====
supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"]
)

slack_client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_USERNAME = os.environ["ODOO_USERNAME"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

SEPAY_SECRET = os.environ["SEPAY_SECRET"]

# ===== ODOO LOGIN =====
common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")


def verify_sepay_signature(body, signature):
    expected = hmac.new(
        SEPAY_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def handler(request):
    if request.method != "POST":
        return {"statusCode": 405, "body": "Method Not Allowed"}

    raw_body = request.body
    signature = request.headers.get("x-sepay-signature", "")

    if not verify_sepay_signature(raw_body, signature):
        return {"statusCode": 403, "body": "Invalid signature"}

    data = json.loads(raw_body)
    trx = data.get("transaction", {})

    transaction_id = trx.get("id")
    amount = float(trx.get("amount_in", 0))
    content = trx.get("transaction_content", "")

    # ===== CHECK DUPLICATE =====
    existing = supabase.table("payment_transactions") \
        .select("*") \
        .eq("sepay_transaction_id", transaction_id) \
        .execute()

    if existing.data:
        return {"statusCode": 200, "body": "Duplicate"}

    # ===== EXTRACT INVOICE =====
    match = re.search(r'(HD\d+)', content)
    invoice_number = match.group(1) if match else None

    so_id = None
    so_name = None
    partner_name = None
    status = "not_match"

    if invoice_number:
        orders = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'sale.order', 'search_read',
            [[['e_invoicenumber', '=', invoice_number]]],
            {'fields': ['id', 'name', 'amount_total', 'partner_id']}
        )

        if orders:
            order = orders[0]
            so_id = order["id"]
            so_name = order["name"]
            partner_name = order["partner_id"][1]

            if float(order["amount_total"]) == amount:
                status = "matched"

    # ===== INSERT LOG =====
    insert_res = supabase.table("payment_transactions").insert({
        "sepay_transaction_id": transaction_id,
        "invoice_number": invoice_number,
        "so_id": so_id,
        "so_name": so_name,
        "amount": amount,
        "status": status,
        "raw_payload": data
    }).execute()

    # ===== SEND SLACK IF MATCHED =====
    if status == "matched":
        message = f"{so_name} - {amount:,.0f} - {invoice_number} - {partner_name} : KHỚP"

        slack_res = slack_client.chat_postMessage(
            channel=os.environ["SLACK_CHANNEL_ID"],
            text=message,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Xác nhận"},
                            "style": "primary",
                            "action_id": "confirm_payment",
                            "value": transaction_id
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Báo sai"},
                            "style": "danger",
                            "action_id": "report_error",
                            "value": transaction_id
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Hủy"},
                            "action_id": "cancel_payment",
                            "value": transaction_id
                        }
                    ]
                }
            ]
        )

        supabase.table("payment_transactions") \
            .update({"slack_ts": slack_res["ts"]}) \
            .eq("sepay_transaction_id", transaction_id) \
            .execute()

    return {"statusCode": 200, "body": "OK"}
