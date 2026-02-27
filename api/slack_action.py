import os
import json
import hmac
import hashlib
import time
import requests
from http.server import BaseHTTPRequestHandler

# ENV
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ===============================
# Helper: Log to Supabase
# ===============================
def log_to_supabase(data):
    try:
        url = f"{SUPABASE_URL}/rest/v1/slack_logs"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print("Supabase log error:", str(e))


# ===============================
# Helper: Verify Slack Signature
# ===============================
def verify_signature(headers, body):
    timestamp = headers.get("X-Slack-Request-Timestamp")
    slack_signature = headers.get("X-Slack-Signature")

    if not timestamp or not slack_signature:
        return False

    # chống replay attack
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False

    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    my_signature = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(my_signature, slack_signature)


# ===============================
# Send message to Slack
# ===============================
def send_message(channel, text):
    try:
        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "channel": channel,
            "text": text
        }
        requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print("Slack send error:", str(e))


# ===============================
# Main Handler (Vercel Required)
# ===============================
class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            # Verify Slack
            if not verify_signature(self.headers, body):
                log_to_supabase({
                    "source": "slack_action",
                    "status": "signature_failed",
                    "payload": body.decode("utf-8"),
                    "error": "Invalid Slack signature"
                })
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"Invalid signature")
                return

            # Parse payload
            parsed = dict(x.split('=') for x in body.decode().split('&'))
            payload = json.loads(requests.utils.unquote(parsed.get("payload")))

            user_id = payload["user"]["id"]
            channel_id = payload["channel"]["id"]
            action_id = payload["actions"][0]["action_id"]
            action_value = payload["actions"][0].get("value")

            # TRẢ 200 NGAY cho Slack
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"")

            # =============================
            # XỬ LÝ LOGIC SAU KHI TRẢ 200
            # =============================

            result_text = ""

            if action_id == "approve_payment":
                result_text = f"✅ Thanh toán đã được duyệt bởi <@{user_id}>"
                status = "approved"

            elif action_id == "reject_payment":
                result_text = f"❌ Thanh toán bị từ chối bởi <@{user_id}>"
                status = "rejected"

            else:
                result_text = f"⚠ Không xác định action: {action_id}"
                status = "unknown_action"

            # Gửi message lại Slack
            send_message(channel_id, result_text)

            # Log success
            log_to_supabase({
                "source": "slack_action",
                "user_id": user_id,
                "channel_id": channel_id,
                "action_id": action_id,
                "action_value": action_value,
                "status": status,
                "payload": payload
            })

        except Exception as e:
            # Log error
            log_to_supabase({
                "source": "slack_action",
                "status": "error",
                "error": str(e)
            })

            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")
