import json
import os
import re
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

app = Flask(__name__)
IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")
DATA_PATH = Path(os.environ.get("LEDGER_DATA_PATH", Path(__file__).with_name("orders.ndjson")))
USD_PER_UNIT = {"USD": Decimal("1"), "EUR": Decimal("1.11"), "INR": Decimal("0.01174")}

def parse_dt(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt

def load_orders():
    rows = []
    with DATA_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    # Keep the row with the latest updated_at for each order ID.
    current = {}
    for row in rows:
        old = current.get(row["id"])
        if old is None or parse_dt(row["updated_at"]).astimezone(UTC) > parse_dt(old["updated_at"]).astimezone(UTC):
            current[row["id"]] = row
    return list(current.values())

ORDERS = load_orders()

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12
}
REGIONS = {"north", "south", "east", "west", "central"}
PRODUCTS = sorted({r["product"] for r in ORDERS}, key=len, reverse=True)
CUSTOMERS = sorted({r["customer"] for r in ORDERS}, key=len, reverse=True)

def norm(s):
    return re.sub(r"\s+", " ", s.lower()).strip()

def find_target_currency(q):
    qn = norm(q)
    for code in ("USD", "EUR", "INR"):
        if re.search(r"\b" + code.lower() + r"\b", qn):
            return code
    if re.search(r"\b(us dollars?|dollars?)\b", qn): return "USD"
    if re.search(r"\beuros?\b", qn): return "EUR"
    if re.search(r"\b(indian rupees?|rupees?)\b", qn): return "INR"
    return "USD"

def filters_from_question(question):
    q = norm(question)
    filters = {}

    for region in REGIONS:
        if re.search(r"\b" + region + r"\b", q):
            filters["region"] = region.title()
            break

    for product in PRODUCTS:
        if product.lower() in q:
            filters["product"] = product
            break

    for customer in CUSTOMERS:
        if customer.lower() in q:
            filters["customer"] = customer
            break

    # Optional explicit status filters, otherwise the metric decides the status.
    for status in ("paid", "refunded", "void"):
        if re.search(r"\b" + status + r"\b", q):
            filters["status"] = status
            break

    # Month + year (business dates are evaluated in Asia/Kolkata).
    month_match = re.search(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\s+(20\d{2})\b", q)
    if month_match:
        filters["month"] = MONTHS[month_match.group(1)]
        filters["year"] = int(month_match.group(2))
    else:
        year_match = re.search(r"\b(20\d{2})\b", q)
        if year_match:
            filters["year"] = int(year_match.group(1))

    # Exact ISO dates or common numeric dates.
    date_tokens = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", q)
    if len(date_tokens) >= 2:
        filters["start_date"] = date.fromisoformat(date_tokens[0])
        filters["end_date"] = date.fromisoformat(date_tokens[1])
    elif len(date_tokens) == 1:
        filters["exact_date"] = date.fromisoformat(date_tokens[0])

    return filters

def business_date(row):
    return parse_dt(row["created_at"]).astimezone(IST).date()

def row_matches(row, filters):
    if "region" in filters and row["region"].lower() != filters["region"].lower(): return False
    if "product" in filters and row["product"].lower() != filters["product"].lower(): return False
    if "customer" in filters and row["customer"].lower() != filters["customer"].lower(): return False
    if "status" in filters and row["status"].lower() != filters["status"]: return False
    d = business_date(row)
    if "year" in filters and d.year != filters["year"]: return False
    if "month" in filters and d.month != filters["month"]: return False
    if "start_date" in filters and d < filters["start_date"]: return False
    if "end_date" in filters and d > filters["end_date"]: return False
    if "exact_date" in filters and d != filters["exact_date"]: return False
    return True

def converted_amount(row, target="USD"):
    source = row["currency"].upper()
    if source not in USD_PER_UNIT or target not in USD_PER_UNIT:
        return Decimal("0")
    # Convert source currency to USD, then from USD to the requested currency.
    usd = Decimal(str(row["amount"])) * USD_PER_UNIT[source]
    return usd / USD_PER_UNIT[target]

def money(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def answer_question(question):
    q = norm(question)
    filters = filters_from_question(question)
    target_currency = find_target_currency(question)

    # Pick the dataset status according to the question's intended metric.
    asks_refund = any(x in q for x in ("refund", "refunded", "reimbursement"))
    asks_void = "void" in q
    asks_count = any(x in q for x in ("how many", "count", "number of"))
    asks_quantity = any(x in q for x in ("quantity", "quantities", "units sold", "items sold"))
    asks_average = any(x in q for x in ("average order value", "average sale", "average revenue"))
    asks_customer_count = "customers" in q and asks_count
    asks_product_list = ("list products" in q or "which products" in q or "what products" in q) and not any(x in q for x in ("revenue", "sales", "units", "sold"))
    asks_region_rank = "which region" in q and any(x in q for x in ("highest", "most", "top", "largest"))
    asks_product_rank = ("which product" in q or "best-selling product" in q or "top product" in q) and any(x in q for x in ("highest", "most", "top", "best-selling", "best selling", "revenue", "sales", "sold"))
    asks_customer_rank = ("which customer" in q or q.startswith("who ")) and any(x in q for x in ("spent most", "highest spending", "most spent", "top customer", "largest customer", "highest revenue"))

    rows = [r for r in ORDERS if row_matches(r, {k:v for k,v in filters.items() if k != "status"})]
    if "status" in filters:
        rows = [r for r in rows if r["status"].lower() == filters["status"]]

    # For revenue metrics, only paid orders count. Refund questions use refunded orders.
    if "status" not in filters:
        if asks_refund:
            rows = [r for r in rows if r["status"] == "refunded"]
        elif asks_void:
            rows = [r for r in rows if r["status"] == "void"]
        elif not asks_count or any(x in q for x in ("revenue", "sales", "spent", "sold", "earning", "income", "profit", "average")):
            rows = [r for r in rows if r["status"] == "paid"]

    if asks_customer_count:
        return len({r["customer"] for r in rows})
    if asks_product_list:
        return sorted({r["product"] for r in rows})

    # Grouped ranking questions.
    if asks_region_rank:
        totals = defaultdict(Decimal)
        for r in rows:
            if r["status"] == "paid":
                totals[r["region"]] += converted_amount(r, target_currency)
        return max(totals, key=totals.get) if totals else None

    if asks_product_rank:
        totals = defaultdict(Decimal)
        for r in rows:
            if asks_quantity:
                totals[r["product"]] += Decimal(str(r["qty"]))
            else:
                if r["status"] == "paid":
                    totals[r["product"]] += converted_amount(r, target_currency)
        return max(totals, key=totals.get) if totals else None

    if asks_customer_rank:
        totals = defaultdict(Decimal)
        for r in rows:
            if r["status"] == "paid":
                totals[r["customer"]] += converted_amount(r, target_currency)
        return max(totals, key=totals.get) if totals else None

    if asks_count:
        if asks_refund:
            return sum(1 for r in rows if r["status"] == "refunded")
        if "order" in q:
            return len(rows)
        if "product" in q:
            return len({r["product"] for r in rows})
        if "customer" in q:
            return len({r["customer"] for r in rows})
        return len(rows)

    if asks_quantity:
        return sum(int(r["qty"]) for r in rows)

    if asks_average:
        if not rows: return 0
        return money(sum((converted_amount(r, target_currency) for r in rows), Decimal("0")) / Decimal(len(rows)))

    # Total monetary metric: refunds vs revenue/sales/spending.
    total = sum((converted_amount(r, target_currency) for r in rows), Decimal("0"))
    if asks_refund or any(x in q for x in ("revenue", "sales", "spent", "spending", "income", "amount", "total", "value", "money", "usd", "eur", "inr")):
        return money(total)

    # A sensible default for a question about the ledger: return paid revenue.
    return money(sum((converted_amount(r, target_currency) for r in rows if r["status"] == "paid"), Decimal("0")))

@app.get("/")
def health():
    return jsonify({"service": "Acme Appliances Ledger Agent", "status": "ok", "current_orders": len(ORDERS)})

@app.post("/")
def ask():
    body = request.get_json(silent=True) or {}
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": 'Send JSON with a non-empty "question" string.'}), 400
    try:
        return jsonify({"answer": answer_question(question)})
    except Exception:
        app.logger.exception("Question processing failed")
        return jsonify({"error": "Could not process this question."}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
