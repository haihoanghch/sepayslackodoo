import os
import json
import hmac
import hashlib
import time
import xmlrpc.client
from supabase import create_client
from slack_sdk import WebClient

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"]
)

slack_client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_USERNAME = os.environ["ODOO_USERNAME"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")


def verify_slack(request):
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    sig_basestring = f"v0:{timestamp}:{request.body.decode()}"
    my_signature = 'v0=' + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    slack_signature = request.headers.get("X-Slack-Signature")
    return hmac.compare_digest(my_signature, slack_signature)


def handler(request):
    if not verify_slack(request):
        return {"statusCode": 403, "body": "Invalid Slack signature"}

    payload = json.loads(request.form["payload"])

    action = payload["actions"][0]["action_id"]
    transaction_id = payload["actions"][0]["value"]
    user_id = payload["user"]["id"]
    channel = payload["channel"]["id"]
    ts = payload["message"]["ts"]

    record = supabase.table("payment_transactions") \
        .select("*") \
        .eq("sepay_transaction_id", transaction_id) \
        .execute()

    if not record.data:
        return {"statusCode": 200, "body": "Not found"}

    payment = record.data[0]

    # delete original message
    slack_client.chat_delete(channel=channel, ts=ts)

    if action == "confirm_payment":
        supabase.table("payment_transactions") \
            .update({
                "status": "confirmed",
                "confirmed_by": user_id
            }) \
            .eq("sepay_transaction_id", transaction_id) \
            .execute()

        # Odoo log note
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            'mail.message', 'create',
            [{
                'model': 'sale.order',
                'res_id': payment["so_id"],
                'body': f'Thanh toán được xác nhận bởi Slack user {user_id}'
            }]
        )

        slack_client.chat_postMessage(
            channel=channel,
            text=f"Đã xác nhận bởi <@{user_id}>"
        )

    elif action == "report_error":
        supabase.table("payment_transactions") \
            .update({"status": "reported"}) \
            .eq("sepay_transaction_id", transaction_id) \
            .execute()

        slack_client.chat_postMessage(
            channel=channel,
            text=f"Đã báo sai bởi <@{user_id}>"
        )

    elif action == "cancel_payment":
        supabase.table("payment_transactions") \
            .update({"status": "canceled"}) \
            .eq("sepay_transaction_id", transaction_id) \
            .execute()

        slack_client.chat_postMessage(
            channel=channel,
            text=f"Đã hủy bởi <@{user_id}>"
        )

    return {"statusCode": 200, "body": "OK"}
