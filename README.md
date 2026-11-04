# Casa Basilico: restaurant ordering

Customers browse a menu, build an order by clicking or chatting, and track it live.
Staff move orders through `placed → preparing → ready → delivered` (or `cancelled`) on a kitchen board.
Flask + SQLite backend, one static HTML/JS page, no build step.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # http://localhost:5000
```

- Customers: open `/`. Staff: click **Kitchen** (token defaults to `staff`).
- Config via env vars: `STAFF_TOKEN` (default `staff`), `DB_PATH` (default `restaurant.db`), `PORT` (default `5000`).
- The database is created and seeded with a sample menu on first start. Delete `restaurant.db` to reset.

## Tests

```bash
python -m pytest -q
```

## API

| Method & path | Who | Notes |
|---|---|---|
| `GET /api/menu` | public | available items |
| `POST /api/orders` | public | `{customer_name, items:[{menu_item_id, quantity}]}` → 201 with server-computed totals |
| `GET /api/orders/<id>` | public | order tracking |
| `GET /api/orders?status=` | staff | newest first, max 100 |
| `PATCH /api/orders/<id>/status` | staff | `{status}`; illegal moves → 409, unknown status → 422 |
| `POST /api/chat` | public | `{message, cart, customer_name}` → `{reply, cart, order}` |

Staff routes need header `X-Staff-Token`. Errors are `{"error": "..."}`.

## Chatbot

Say things like “two margherita pizzas and a cola”, “add a tiramisu”, “no cola”, “what's on the menu?”,
then “confirm” to place the order. It is rule-based (see `chat.py`), so it needs no API key.
