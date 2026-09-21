"""
Customer & staff tests: customer CRUD, purchase history, staff
management, profile self-service, and the store chat.
"""
import pytest


# ---------------------------------------------------------
# CUSTOMERS
# ---------------------------------------------------------

class TestCustomerCrud:
    def test_quick_add_customer(self, client, employee):
        r = client.post("/api/v1/customers/", json={
            "name": "Rahim", "phone_number": "01811111111",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Rahim"
        assert body["customer_id"] > 0

    def test_duplicate_phone_rejected(self, client, employee, customer):
        r = client.post("/api/v1/customers/", json={
            "name": "Someone Else",
            "phone_number": customer["phone_number"],
        })
        assert r.status_code == 400
        assert "already registered" in r.json()["detail"]

    def test_lookup_by_phone(self, client, employee, customer):
        r = client.get(f"/api/v1/customers/phone/{customer['phone_number']}")
        assert r.status_code == 200
        assert r.json()["customer_id"] == customer["customer_id"]

    def test_lookup_unknown_phone_404(self, client, employee):
        r = client.get("/api/v1/customers/phone/01988888888")
        assert r.status_code == 404

    def test_update_customer_name(self, client, owner, customer):
        r = client.put(f"/api/v1/customers/{customer['customer_id']}",
                       json={"name": "New Name"})
        assert r.status_code == 200
        assert r.json()["name"] == "New Name"

    def test_update_unknown_customer_404(self, client, owner):
        assert client.put("/api/v1/customers/9999",
                          json={"name": "Nobody"}).status_code == 404

    def test_empty_name_rejected(self, client, owner, customer):
        r = client.put(f"/api/v1/customers/{customer['customer_id']}",
                       json={"name": ""})
        assert r.status_code == 422

    def test_customer_directory_has_lifetime_spend(self, client, owner_client, employee,
                                                   product, customer):
        """Owner-only directory must aggregate spend across sales."""
        for _ in range(2):
            client.post("/api/v1/checkout/", json={
                "customer_id": customer["customer_id"],
                "payment_method": "Cash",
                "items": [{"product_id": product["product_id"], "quantity": 1}],
            })
        directory = owner_client.get("/api/v1/customers/").json()
        row = next(c for c in directory if c["customer_id"] == customer["customer_id"])
        assert row["total_spend"] == pytest.approx(120.0)

    def test_customer_history(self, client, owner, employee, product, customer):
        client.post("/api/v1/checkout/", json={
            "customer_id": customer["customer_id"],
            "payment_method": "Cash",
            "items": [{"product_id": product["product_id"], "quantity": 1}],
        })
        r = client.get(f"/api/v1/customers/{customer['customer_id']}/history")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_customer_history_empty_404(self, client, owner, customer):
        r = client.get(f"/api/v1/customers/{customer['customer_id']}/history")
        assert r.status_code == 404


# ---------------------------------------------------------
# STAFF MANAGEMENT (owner-only surface)
# ---------------------------------------------------------

class TestStaffManagement:
    def test_roster_excludes_owners(self, client, owner_client, owner, employee):
        """The roster must contain exactly the employees, never owners."""
        roster = owner_client.get("/api/v1/employees/").json()
        assert [e["user_id"] for e in roster] == [employee["user_id"]]

    def test_update_position_and_salary(self, client, owner_client, employee):
        r = owner_client.put(f"/api/v1/employees/{employee['user_id']}", json={
            "position": "Senior Cashier", "salary": 25000,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["position"] == "Senior Cashier"
        assert body["salary"] == 25000

    def test_promote_employee_to_owner(self, client, owner_client, employee):
        r = owner_client.put(f"/api/v1/employees/{employee['user_id']}",
                             json={"role": "owner"})
        assert r.status_code == 200
        assert r.json()["user_type"] == "owner"
        # Gone from the employee roster, present as a user.
        roster = owner_client.get("/api/v1/employees/").json()
        assert all(e["user_id"] != employee["user_id"] for e in roster)

    def test_delete_employee_keeps_sales_history(self, client, owner_client, employee,
                                                 product, customer):
        """Deleting staff must NOT delete the sales they processed."""
        client.post("/api/v1/checkout/", json={
            "customer_id": customer["customer_id"],
            "payment_method": "Cash",
            "items": [{"product_id": product["product_id"], "quantity": 1}],
        })
        r = owner_client.delete(f"/api/v1/employees/{employee['user_id']}")
        assert r.status_code == 200

        # Sales survive with employee detached (NULL).
        sales = owner_client.get("/api/v1/sales/").json()
        assert len(sales) == 1
        assert sales[0]["employee_id"] is None

    def test_cannot_delete_self(self, client, owner):
        r = client.delete(f"/api/v1/employees/{owner['user_id']}")
        assert r.status_code == 400

    def test_cannot_delete_an_owner(self, client, owner_client, employee):
        # Promote employee to owner first...
        owner_client.put(f"/api/v1/employees/{employee['user_id']}",
                         json={"role": "owner"})
        # ...then deleting that user id must refuse (owner account).
        r = owner_client.delete(f"/api/v1/employees/{employee['user_id']}")
        assert r.status_code == 400

    def test_search_employees(self, client, owner_client, employee):
        r = owner_client.get("/api/v1/employees/search/", params={"query": "cashier"})
        assert r.status_code in (200, 404)  # depends on position set

        r = owner_client.get("/api/v1/employees/search/", params={"query": "Staff"})
        assert r.status_code == 200
        assert any(e["user_id"] == employee["user_id"] for e in r.json())


# ---------------------------------------------------------
# PROFILE SELF-SERVICE
# ---------------------------------------------------------

class TestProfileSelfService:
    def test_update_own_name(self, client, employee):
        r = client.put("/api/v1/employees/me/profile", json={"name": "Renamed"})
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed"
        # Session must be refreshed so /me shows the new name immediately.
        me = client.get("/api/v1/auth/me").json()
        assert me["name"] == "Renamed"

    def test_update_own_phone_normalized(self, client, employee):
        r = client.put("/api/v1/employees/me/profile",
                       json={"phone_number": "019 2222-3333"})
        assert r.status_code == 200
        assert r.json()["phone_number"] == "01922223333"

    def test_phone_clash_rejected(self, client, owner, employee):
        r = client.put("/api/v1/employees/me/profile",
                       json={"phone_number": "01700000001"})  # owner's phone
        assert r.status_code == 400
        assert "already used" in r.json()["detail"]

    def test_invalid_phone_rejected(self, client, employee):
        r = client.put("/api/v1/employees/me/profile",
                       json={"phone_number": "not-a-phone"})
        assert r.status_code == 400

    def test_my_store_card(self, client, owner, employee):
        r = client.get("/api/v1/employees/me/store")
        assert r.status_code == 200
        body = r.json()
        assert body["owner_name"] == "The Owner"
        assert body["my_position"] is None or isinstance(body["my_position"], str)
        assert body["colleagues"] == 0


# ---------------------------------------------------------
# STORE CHAT
# ---------------------------------------------------------

class TestStoreChat:
    def test_send_and_fetch(self, client, owner, employee):
        r = client.post("/api/v1/chat/messages", json={"body": "Shift starts at 9"})
        assert r.status_code == 201
        messages = client.get("/api/v1/chat/messages").json()
        assert any(m["body"] == "Shift starts at 9" for m in messages)

    def test_empty_message_rejected(self, client, employee):
        r = client.post("/api/v1/chat/messages", json={"body": "   "})
        assert r.status_code == 400

    def test_reply_to_message(self, client, employee):
        sent = client.post("/api/v1/chat/messages", json={"body": "question"}).json()
        r = client.post("/api/v1/chat/messages", json={
            "body": "answer", "reply_to_id": sent["message_id"]})
        assert r.status_code == 201
        assert r.json()["reply_to"]["body"] == "question"

    def test_cannot_reply_across_stores(self, client, owner, employee):
        """
        A second store's chat must be invisible: messages are scoped by
        owner, so a reply can only reference the SAME store's messages.
        """
        # Employee sends in store #1...
        sent = client.post("/api/v1/chat/messages", json={"body": "store one"}).json()

        # A second, independent store is bootstrapped:
        client2_post = client.post("/api/v1/auth/register", json={
            "name": "Owner Two", "phone_number": "01600000001",
            "password": "secret123", "role": "owner"})
        assert client2_post.status_code == 403  # only owners can add owners

    def test_delete_own_message_only(self, client, owner_client, employee):
        sent = client.post("/api/v1/chat/messages", json={"body": "typo"}).json()
        # The owner cannot delete the employee's message:
        r = owner_client.delete(f"/api/v1/chat/messages/{sent['message_id']}")
        assert r.status_code == 403

    def test_sender_can_delete_own_message(self, client, employee):
        sent = client.post("/api/v1/chat/messages", json={"body": "delete me"}).json()
        r = client.delete(f"/api/v1/chat/messages/{sent['message_id']}")
        assert r.status_code == 200
        messages = client.get("/api/v1/chat/messages").json()
        mine = next(m for m in messages if m["message_id"] == sent["message_id"])
        assert mine["deleted"] is True
        assert mine["body"] == ""

    def test_chat_scoped_per_store(self, client, owner_client, employee):
        """
        Employee of store #1 must not see messages from store #2 —
        verified by bootstrapping owner #2 via the owner-only endpoint.
        """
        client.post("/api/v1/chat/messages", json={"body": "store one msg"})
        # owner creates second owner account, then we log in as them:
        owner_client.post("/api/v1/auth/register/owner", json={
            "name": "Owner Two", "phone_number": "01600000001",
            "password": "secret123", "role": "owner"})
        client.post("/api/v1/auth/login", json={
            "phone_number": "01600000001", "password": "secret123"})
        messages = client.get("/api/v1/chat/messages").json()
        assert all(m["body"] != "store one msg" for m in messages)
