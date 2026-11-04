import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import create_app

H = {"X-Staff-Token": "staff"}


@pytest.fixture
def c(tmp_path):
    return create_app(str(tmp_path / "t.db")).test_client()


def ids(c):
    return {m["name"]: m["id"] for m in c.get("/api/menu").get_json()}


def place(c, items, name="Ana"):
    return c.post("/api/orders", json={"customer_name": name, "items": items})


def test_server_computes_total_and_ignores_client_prices(c):
    m = ids(c)
    r = place(c, [{"menu_item_id": m["Margherita Pizza"], "quantity": 2, "price_cents": 1},
                  {"menu_item_id": m["Cola"], "quantity": 1}])
    o = r.get_json()
    assert r.status_code == 201
    assert (o["subtotal_cents"], o["tax_cents"], o["total_cents"]) == (2700, 223, 2923)


@pytest.mark.parametrize("items", [[], [{"menu_item_id": 1, "quantity": 0}], [{"menu_item_id": 999, "quantity": 1}],
                                   [{"menu_item_id": 1, "quantity": True}], "pizza"])
def test_invalid_orders_rejected(c, items):
    assert place(c, items).status_code == 422


def test_status_flow_and_rejections(c):
    oid = place(c, [{"menu_item_id": 1, "quantity": 1}]).get_json()["id"]
    url = f"/api/orders/{oid}/status"
    assert c.patch(url, json={"status": "ready"}, headers=H).status_code == 409   # skipping a step
    assert c.patch(url, json={"status": "bogus"}, headers=H).status_code == 422
    for s in ["preparing", "ready", "delivered"]:
        assert c.patch(url, json={"status": s}, headers=H).status_code == 200
    assert c.patch(url, json={"status": "preparing"}, headers=H).status_code == 409  # no going back
    assert c.patch(url, json={"status": "cancelled"}, headers=H).status_code == 409


def test_cancel_allowed_early_and_final(c):
    oid = place(c, [{"menu_item_id": 1, "quantity": 1}]).get_json()["id"]
    url = f"/api/orders/{oid}/status"
    assert c.patch(url, json={"status": "cancelled"}, headers=H).status_code == 200
    assert c.patch(url, json={"status": "preparing"}, headers=H).status_code == 409


def test_staff_endpoints_need_token(c):
    assert c.get("/api/orders").status_code == 401
    assert c.patch("/api/orders/1/status", json={"status": "preparing"}).status_code == 401
    assert c.get("/api/orders", headers=H).status_code == 200


def test_chat_builds_cart_then_places_order(c):
    r = c.post("/api/chat", json={"message": "I'd like two margherita pizzas and a cola", "cart": []}).get_json()
    q = {i["menu_item_id"]: i["quantity"] for i in r["cart"]}
    m = ids(c)
    assert q == {m["Margherita Pizza"]: 2, m["Cola"]: 1}
    r = c.post("/api/chat", json={"message": "no cola", "cart": r["cart"]}).get_json()
    assert len(r["cart"]) == 1
    r = c.post("/api/chat", json={"message": "confirm", "cart": r["cart"], "customer_name": "Avi"}).get_json()
    assert r["order"]["total_cents"] == 2598 and r["cart"] == []  # 2400 + 8.25 % tax
