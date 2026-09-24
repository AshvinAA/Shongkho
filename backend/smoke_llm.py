"""
One-off smoke test: real Gemini call through the insight engine.
Run from backend/:  python smoke_llm.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from analytics import insights, llm  # noqa: E402

print("key set:", bool(llm.api_key()), "| model:", llm.model_name(),
      "| budget:", llm.budget_seconds(), "s")

# Synthetic but realistic bundle — exact payload shapes the pipeline produces.
sales = {
    "period": "week",
    "best_unit": "days",
    "current": {"revenue": 14200.0, "profit": 4200.0, "orders": 87},
    "previous": {"revenue": 12600.0, "profit": 3900.0, "orders": 80},
    "change_pct": {"revenue": 12.7, "profit": 7.7, "orders": 8.8},
    "series": [],
    "best": {"by_revenue": [], "by_profit": []},
    "window": {"current_start": "2026-09-21T00:00:00", "current_end": "2026-09-28T00:00:00",
               "previous_start": "2026-09-14T00:00:00", "previous_end": "2026-09-21T00:00:00"},
}
employees = {"employees": [
    {"employee_id": 2, "name": "Rahim", "orders": 30, "revenue": 8000.0, "profit": 2400.0,
     "change_pct": {"revenue": 14.3, "profit": 9.1, "orders": 11.1}},
    {"employee_id": 3, "name": "Karim", "orders": 18, "revenue": 3500.0, "profit": 1000.0,
     "change_pct": {"revenue": -12.5, "profit": -20.0, "orders": -10.0}},
], "race_series": {"keys": [], "labels": [], "revenue": {}, "profit": {}}}
products = {"top_by_revenue": [
    {"product_id": 1, "name": "Mustard Oil 1L", "units": 40, "revenue": 5600.0,
     "profit": 1400.0, "margin_pct": 25.0, "units_change_pct": 33.3},
    {"product_id": 2, "name": "Sugar 1kg", "units": 22, "revenue": 2420.0,
     "profit": 480.0, "margin_pct": 19.8, "units_change_pct": None},
], "top_by_profit": [], "bottom_by_revenue": []}

bundle = insights.build_context(sales, [], employees_payload=employees,
                                products_payload=products)
out = insights.build_insights(bundle, "week")
print(json.dumps(out, indent=2, ensure_ascii=False))
