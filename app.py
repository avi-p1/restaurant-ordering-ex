"""Restaurant ordering: Flask + SQLite. Run: python app.py"""
import hmac
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, g, jsonify, request

import chat as bot

TAX_BPS = 825  # 8.25 %, applied server-side only
FLOW = {  # the only legal status changes
    "placed": {"preparing", "cancelled"},
    "preparing": {"ready", "cancelled"},
    "ready": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS menu_items(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
  price_cents INTEGER NOT NULL CHECK(price_cents >= 0), category TEXT NOT NULL,
  aliases TEXT NOT NULL DEFAULT '', available INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, customer_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'placed'
    CHECK(status IN ('placed','preparing','ready','delivered','cancelled')),
  subtotal_cents INTEGER NOT NULL, tax_cents INTEGER NOT NULL, total_cents INTEGER NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  menu_item_id INTEGER NOT NULL REFERENCES menu_items(id), name TEXT NOT NULL,
  unit_price_cents INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 20));
"""
SEED = [
    ("Margherita Pizza", "Tomato, fior di latte, basil", 1200, "Pizza", "margherita"),
    ("Pepperoni Pizza", "Tomato, mozzarella, spicy pepperoni", 1400, "Pizza", "pepperoni"),
    ("Caesar Salad", "Romaine, parmesan, sourdough crumb", 900, "Starters", "caesar,salad"),
    ("Garlic Bread", "Wood-fired, salted butter", 600, "Starters", "garlic bread,bread"),
    ("Spaghetti Carbonara", "Guanciale, egg yolk, pecorino", 1350, "Pasta", "carbonara,spaghetti"),
    ("Tiramisu", "Espresso-soaked, mascarpone", 700, "Dessert", "tiramisu"),
    ("Cola", "330 ml, over ice", 300, "Drinks", "cola,coke"),
    ("Lemonade", "House-squeezed", 350, "Drinks", "lemonade"),
    ("Sparkling Water", "500 ml", 250, "Drinks", "water,sparkling water"),
]


class ApiError(Exception):
    def __init__(self, status, msg):
        self.status, self.msg = status, msg


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_order(conn, name, raw):
    """Validate input, price from the DB (never from the client), insert atomically."""
    name = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(name) <= 60:
        raise ApiError(422, "customer_name is required (max 60 characters)")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ApiError(422, "items must be a non-empty list")
    qty = {}
    for it in raw:
        mid = it.get("menu_item_id") if isinstance(it, dict) else None
        q = it.get("quantity") if isinstance(it, dict) else None
        if type(mid) is not int or type(q) is not int or not 1 <= q <= 20:
            raise ApiError(422, "each item needs an integer menu_item_id and a quantity from 1 to 20")
        qty[mid] = qty.get(mid, 0) + q
    lines = []
    for mid, q in qty.items():
        row = conn.execute("SELECT * FROM menu_items WHERE id=?", (mid,)).fetchone()
        if not row:
            raise ApiError(422, f"menu item {mid} does not exist")
        if not row["available"]:
            raise ApiError(422, f"{row['name']} is not available")
        if q > 20:
            raise ApiError(422, f"at most 20 of {row['name']} per order")
        lines.append((row, q))
    subtotal = sum(r["price_cents"] * q for r, q in lines)
    tax = (subtotal * TAX_BPS + 5000) // 10000  # round half up
    ts = now()
    with conn:
        cur = conn.execute(
            "INSERT INTO orders(customer_name,subtotal_cents,tax_cents,total_cents,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)", (name, subtotal, tax, subtotal + tax, ts, ts))
        conn.executemany(
            "INSERT INTO order_items(order_id,menu_item_id,name,unit_price_cents,quantity) VALUES(?,?,?,?,?)",
            [(cur.lastrowid, r["id"], r["name"], r["price_cents"], q) for r, q in lines])
    return cur.lastrowid


def order_json(conn, row):
    d = dict(row)
    d["items"] = [dict(i) for i in conn.execute(
        "SELECT menu_item_id,name,unit_price_cents,quantity FROM order_items WHERE order_id=? ORDER BY id",
        (row["id"],))]
    return d


def create_app(db_path=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    path = db_path or os.environ.get("DB_PATH", "restaurant.db")
    token = os.environ.get("STAFF_TOKEN", "staff")

    boot = sqlite3.connect(path)
    boot.executescript(SCHEMA)
    if not boot.execute("SELECT 1 FROM menu_items").fetchone():
        boot.executemany("INSERT INTO menu_items(name,description,price_cents,category,aliases) VALUES(?,?,?,?,?)", SEED)
    boot.commit()
    boot.close()

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(path, timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys=ON")
        return g.db

    @app.teardown_appcontext
    def close(_):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify(error=e.msg), e.status

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="not found"), 404

    def staff(fn):
        @wraps(fn)
        def wrapper(*a, **k):
            given = request.headers.get("X-Staff-Token", "").encode()
            if not hmac.compare_digest(given, token.encode()):
                raise ApiError(401, "staff token required")
            return fn(*a, **k)
        return wrapper

    def body():
        b = request.get_json(silent=True)
        return b if isinstance(b, dict) else {}

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/menu")
    def menu():
        rows = db().execute("SELECT id,name,description,price_cents,category FROM menu_items WHERE available=1 ORDER BY id")
        return jsonify([dict(r) for r in rows])

    @app.post("/api/orders")
    def place_order():
        b = body()
        conn = db()
        oid = create_order(conn, b.get("customer_name"), b.get("items"))
        row = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        return jsonify(order_json(conn, row)), 201

    @app.get("/api/orders/<int:oid>")
    def get_order(oid):
        conn = db()
        row = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not row:
            raise ApiError(404, "order not found")
        return jsonify(order_json(conn, row))

    @app.get("/api/orders")
    @staff
    def list_orders():
        status = request.args.get("status")
        if status and status not in FLOW:
            raise ApiError(422, f"status must be one of {', '.join(FLOW)}")
        conn = db()
        sql, args = "SELECT * FROM orders", ()
        if status:
            sql, args = sql + " WHERE status=?", (status,)
        rows = conn.execute(sql + " ORDER BY id DESC LIMIT 100", args).fetchall()
        return jsonify([order_json(conn, r) for r in rows])

    @app.patch("/api/orders/<int:oid>/status")
    @staff
    def set_status(oid):
        new = body().get("status")
        if not isinstance(new, str) or new not in FLOW:
            raise ApiError(422, f"status must be one of {', '.join(FLOW)}")
        conn = db()
        row = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not row:
            raise ApiError(404, "order not found")
        if new not in FLOW[row["status"]]:
            allowed = ", ".join(sorted(FLOW[row["status"]])) or "none"
            raise ApiError(409, f"cannot move order from {row['status']} to {new} (allowed: {allowed})")
        with conn:  # compare-and-set: a concurrent change makes this update match zero rows
            n = conn.execute("UPDATE orders SET status=?, updated_at=? WHERE id=? AND status=?",
                             (new, now(), oid, row["status"])).rowcount
        if n == 0:
            raise ApiError(409, "order status changed concurrently; reload and retry")
        row = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        return jsonify(order_json(conn, row))

    @app.post("/api/chat")
    def chat():
        b = body()
        conn = db()
        menu_rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM menu_items WHERE available=1")}
        cart = {}
        for it in b.get("cart") if isinstance(b.get("cart"), list) else []:
            mid = it.get("menu_item_id") if isinstance(it, dict) else None
            q = it.get("quantity") if isinstance(it, dict) else None
            if type(mid) is int and type(q) is int and mid in menu_rows and 1 <= q <= 20:
                cart[mid] = q
        result = bot.handle(str(b.get("message", ""))[:500], cart, menu_rows)
        order = None
        if result["confirm"]:
            name = b.get("customer_name") if isinstance(b.get("customer_name"), str) and b["customer_name"].strip() else "Guest"
            oid = create_order(conn, name, [{"menu_item_id": i, "quantity": q} for i, q in result["cart"].items()])
            order = order_json(conn, conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())
            result["cart"] = {}
            result["reply"] = f"Order #{oid} is in for {order['customer_name']}. Total {bot.money(order['total_cents'])}. The kitchen has it."
        return jsonify(reply=result["reply"], order=order,
                       cart=[{"menu_item_id": i, "quantity": q} for i, q in result["cart"].items()])

    return app


if __name__ == "__main__":
    create_app().run(port=int(os.environ.get("PORT", 5000)))
