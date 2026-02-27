data = request.json()
trx = data["transaction"]

transaction_id = trx["id"]
amount = float(trx["amount_in"])
content = trx["transaction_content"]

# 1. chống trùng
if transaction_id exists in supabase:
    return "duplicate"

# 2. tìm invoice number
invoice_number = extract_regex(content)

# 3. gọi Odoo search sale.order
order = search_by_e_invoicenumber(invoice_number)

if not order:
    status = "not_match"
else:
    if float(order["amount_total"]) == amount:
        status = "matched"
    else:
        status = "not_match"

# 4. insert supabase
insert payment_transactions

# 5. nếu matched → gửi Slack interactive message
