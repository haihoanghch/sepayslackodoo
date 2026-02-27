from supabase import create_client
import os
import traceback

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def handler(request):
    data = {}
    try:
        data = request.json()

        # 1️⃣ Ghi log nhận webhook
        supabase.table("sepay_logs").insert({
            "source": "sepay",
            "status": "RECEIVED",
            "transaction_id": data.get("transaction_id"),
            "raw": data
        }).execute()

        # 2️⃣ Validate bắt buộc
        if not data.get("transaction_id"):
            raise Exception("Missing transaction_id")

        if not data.get("amount"):
            raise Exception("Missing amount")

        # 3️⃣ TODO: xử lý match invoice Odoo ở đây

        # 4️⃣ Update trạng thái thành SUCCESS
        supabase.table("sepay_logs") \
            .update({"status": "SUCCESS"}) \
            .eq("transaction_id", data.get("transaction_id")) \
            .execute()

        return "OK"

    except Exception as e:

        error_message = str(e)
        error_stack = traceback.format_exc()

        # 🔴 Ghi vào bảng lỗi
        supabase.table("sepay_error_logs").insert({
            "transaction_id": data.get("transaction_id"),
            "error_message": error_message,
            "error_stack": error_stack,
            "raw": data
        }).execute()

        return "ERROR", 500
