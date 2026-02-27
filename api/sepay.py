import os
import json
import requests
from http.server import BaseHTTPRequestHandler

# ==============================
# ENV VARIABLES
# ==============================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

# ==============================
# LOG TO SUPABASE
# ==============================
def log_to_supabase(data):
    try:
        url = f"{SUPABASE_URL}/rest/v1/sepay_logs"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print("Supabase log error:", str(e))


# ==============================
# SEND MESSAGE TO SLACK
# ==============================
def send_to_slack(text):
    try:
        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "channel": "#general",  # đổi channel nếu cần
            "text": text
        }
        requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print("Slack send error:", str(e))


# ==============================
# MAIN HANDLER
# ==============================
class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            # Parse JSON
            data = json.loads(body.decode("utf-8"))

            # Trả 200 ngay cho Sepay
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

            # ==========================
            # XỬ LÝ SAU KHI TRẢ 200
            # ==========================

            # Hỗ trợ 2 format phổ biến
            if "data" in data:
                payload = data["data"]
            else:
                payload = data

            transaction_id = payload.get("transaction_id")
            amount = payload.get("amount")
            content = payload.get("content") or payload.get("description")
            bank_account = payload.get("bank_account") or payload.get("account_number")
            transfer_time = payload.get("transfer_time")

            # Log vào Supabase
            log_to_supabase({
                "source": "sepay",
                "status": "received",
                "transaction_id": transaction_id,
                "amount": amount,
                "content": content,
                "bank_account": bank_account,
                "transfer_time": transfer_time,
                "raw_payload": payload
            })

            # Gửi Slack thông báo
            slack_message = (
                f"💰 Có giao dịch mới\n"
                f"Transaction: {transaction_id}\n"
                f"Số tiền: {amount}\n"
                f"Nội dung: {content}"
            )

            send_to_slack(slack_message)

        except Exception as e:
            log_to_supabase({
                "source": "sepay",
                "status": "error",
                "error": str(e)
            })

            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")
