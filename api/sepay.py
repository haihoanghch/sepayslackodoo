from supabase import create_client
import os

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def handler(request):
    try:
        data = request.json()

        supabase.table("sepay_logs").insert({
            "source": "sepay",
            "status": "RECEIVED",
            "transaction_id": data.get("transaction_id"),
            "amount": data.get("amount"),
            "content": data.get("content"),
            "bank_account": data.get("bank_account"),
            "transfer_time": data.get("transfer_time"),
            "raw": data
        }).execute()

        return "OK"

    except Exception as e:
        return str(e), 500
