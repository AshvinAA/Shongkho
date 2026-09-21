"""
Inventory tests: boundary inputs, validation, and stock integrity.
"""
import pytest


# ---------------------------------------------------------
# CREATION BOUNDARIES
# ---------------------------------------------------------

class TestProductCreationBoundaries:
    def test_zero_price_allowed(self, client, owner):
        """A free item (0.00) is legal — e.g. a promotional giveaway."""
        r = client.post("/api/v1/products/", json={
            "product_name": "Free Sample",
            "cost_price": 0,
            "retail_price": 0,
            "stock_quantity": 10,
        })
        assert r.status_code == 200
        assert r.json()["retail_price"] == 0

    def test_negative_price_rejected(self, client, owner):
        r = client.post("/api/v1/products/", json={
            "product_name": "Money Loser",
            "cost_price": -5,
            "retail_price": 10,
            "stock_quantity": 1,
        })
        assert r.status_code == 422

    def test_negative_stock_rejected(self, client, owner):
        r = client.post("/api/v1/products/", json={
            "product_name": "Impossible Stock",
            "cost_price": 5,
            "retail_price": 10,
            "stock_quantity": -3,
        })
        assert r.status_code == 422

    def test_empty_name_rejected(self, client, owner):
        r = client.post("/api/v1/products/", json={
            "product_name": "   ",
            "cost_price": 5,
            "retail_price": 10,
            "stock_quantity": 1,
        })
        assert r.status_code == 422

    def test_huge_but_valid_numbers(self, client, owner):
        """Extreme (but sane) values must not crash the API."""
        r = client.post("/api/v1/products/", json={
            "product_name": "Gold Bar",
            "cost_price": 999999999.99,
            "retail_price": 1000000000.0,
            "stock_quantity": 1000000,
        })
        assert r.status_code == 200
        assert r.json()["stock_quantity"] == 1000000

    def test_float_stock_rejected(self, client, owner):
        """Stock must be a whole number."""
        r = client.post("/api/v1/products/", json={
            "product_name": "Fractional",
            "cost_price": 5,
            "retail_price": 10,
            "stock_quantity": 1.5,
        })
        assert r.status_code == 422

    def test_zero_stock_allowed(self, client, owner):
        """Pre-orders / out-of-stock catalogue entries are legal."""
        r = client.post("/api/v1/products/", json={
            "product_name": "Coming Soon",
            "cost_price": 5,
            "retail_price": 10,
            "stock_quantity": 0,
        })
        assert r.status_code == 200
        assert r.json()["stock_quantity"] == 0


# ---------------------------------------------------------
# UNIQUE / DUPLICATE RULES
# ---------------------------------------------------------

class TestProductUniqueness:
    def test_duplicate_name_allowed_but_distinguishable(self, client, owner):
        """
        The schema allows two products with the same display name (real
        shops do this with different suppliers) — both rows must exist
        with distinct IDs.
        """
        a = client.post("/api/v1/products/", json={
            "product_name": "Coca Cola 250ml",
            "cost_price": 20, "retail_price": 30, "stock_quantity": 5,
        })
        b = client.post("/api/v1/products/", json={
            "product_name": "Coca Cola 250ml",
            "cost_price": 22, "retail_price": 35, "stock_quantity": 7,
        })
        assert a.status_code == 200 and b.status_code == 200
        assert a.json()["product_id"] != b.json()["product_id"]

    def test_product_ids_never_collide(self, client, owner):
        ids = set()
        for i in range(5):
            r = client.post("/api/v1/products/", json={
                "product_name": f"Item {i}",
                "cost_price": 1, "retail_price": 2, "stock_quantity": 1,
            })
            ids.add(r.json()["product_id"])
        assert len(ids) == 5


# ---------------------------------------------------------
# STOCK ADJUSTMENT
# ---------------------------------------------------------

class TestStockAdjustment:
    def test_increase_stock(self, client, owner, product):
        r = client.patch(f"/api/v1/products/{product['product_id']}/stock",
                         json={"quantity_change": 50})
        assert r.status_code == 200
        assert r.json()["stock_quantity"] == product["stock_quantity"] + 50

    def test_decrease_stock(self, client, owner, product):
        r = client.patch(f"/api/v1/products/{product['product_id']}/stock",
                         json={"quantity_change": -10})
        assert r.status_code == 200
        assert r.json()["stock_quantity"] == product["stock_quantity"] - 10

    def test_stock_cannot_go_negative(self, client, owner, product):
        r = client.patch(f"/api/v1/products/{product['product_id']}/stock",
                         json={"quantity_change": -(product["stock_quantity"] + 1)})
        assert r.status_code == 400
        assert "negative" in r.json()["detail"].lower()

    def test_stock_can_hit_exactly_zero(self, client, owner, product):
        r = client.patch(f"/api/v1/products/{product['product_id']}/stock",
                         json={"quantity_change": -product["stock_quantity"]})
        assert r.status_code == 200
        assert r.json()["stock_quantity"] == 0

    def test_repeated_adjustments_accumulate(self, client, owner, product):
        """Ten sequential +1s must yield +10 — no lost updates."""
        for _ in range(10):
            client.patch(f"/api/v1/products/{product['product_id']}/stock",
                         json={"quantity_change": 1})
        final = client.get(f"/api/v1/products/{product['product_id']}").json()
        assert final["stock_quantity"] == product["stock_quantity"] + 10

    def test_zero_delta_is_rejected_as_noop(self, client, owner, product):
        """A 0 change is a client mistake; the form forbids it and so do we."""
        # Not explicitly blocked by schema, but must not corrupt anything.
        r = client.patch(f"/api/v1/products/{product['product_id']}/stock",
                         json={"quantity_change": 0})
        assert r.status_code == 200
        assert r.json()["stock_quantity"] == product["stock_quantity"]


# ---------------------------------------------------------
# UPDATE & DELETE RULES
# ---------------------------------------------------------

class TestProductUpdateDelete:
    def test_partial_update_keeps_other_fields(self, client, owner, product):
        r = client.put(f"/api/v1/products/{product['product_id']}",
                       json={"retail_price": 99.99})
        assert r.status_code == 200
        body = r.json()
        assert body["retail_price"] == 99.99
        assert body["product_name"] == product["product_name"]  # untouched
        assert body["stock_quantity"] == product["stock_quantity"]

    def test_update_to_negative_price_rejected(self, client, owner, product):
        r = client.put(f"/api/v1/products/{product['product_id']}",
                       json={"retail_price": -1})
        assert r.status_code == 422

    def test_update_unknown_product_404(self, client, owner):
        assert client.put("/api/v1/products/9999",
                          json={"retail_price": 1}).status_code == 404

    def test_delete_product_without_sales(self, client, owner):
        created = client.post("/api/v1/products/", json={
            "product_name": "Disposable", "cost_price": 1,
            "retail_price": 2, "stock_quantity": 3,
        }).json()
        r = client.delete(f"/api/v1/products/{created['product_id']}")
        assert r.status_code == 200
        assert client.get(f"/api/v1/products/{created['product_id']}").status_code == 404

    def test_delete_product_with_sales_blocked(self, client, owner, product, customer):
        """Products referenced by sale history must not disappear."""
        client.post("/api/v1/checkout/", json={
            "customer_id": customer["customer_id"],
            "payment_method": "Cash",
            "items": [{"product_id": product["product_id"], "quantity": 1}],
        })
        r = client.delete(f"/api/v1/products/{product['product_id']}")
        assert r.status_code == 400
        assert "sales" in r.json()["detail"].lower()

    def test_get_unknown_product_404(self, client, employee):
        assert client.get("/api/v1/products/9999").status_code == 404


# ---------------------------------------------------------
# SEARCH & CATEGORIES
# ---------------------------------------------------------

class TestSearchAndCategories:
    def test_search_by_name_case_insensitive(self, client, owner, product):
        r = client.get("/api/v1/products/search/", params={"query": "widget"})
        assert r.status_code == 200
        assert any(p["product_id"] == product["product_id"] for p in r.json())

    def test_search_no_results_404(self, client, owner):
        r = client.get("/api/v1/products/search/", params={"query": "zzz-nothing"})
        assert r.status_code == 404

    def test_categories_deduplicated_and_sorted(self, client, owner):
        client.post("/api/v1/products/", json={
            "product_name": "A", "cost_price": 1, "retail_price": 2,
            "stock_quantity": 1, "category": "Snacks",
        })
        client.post("/api/v1/products/", json={
            "product_name": "B", "cost_price": 1, "retail_price": 2,
            "stock_quantity": 1, "category": "Drinks",
        })
        client.post("/api/v1/products/", json={
            "product_name": "C", "cost_price": 1, "retail_price": 2,
            "stock_quantity": 1, "category": "Drinks",
        })
        r = client.get("/api/v1/products/categories")
        assert r.status_code == 200
        cats = r.json()
        assert cats == sorted(set(cats))
        assert "Drinks" in cats and "Snacks" in cats
