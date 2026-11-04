# Design note

**Stack.** Flask + SQLite (stdlib `sqlite3`) and a single static page in vanilla JS. One process, one dependency, runs anywhere Python does.

**Server is the authority.** Clients send only `menu_item_id` and `quantity`. Prices come from the database, are snapshotted into `order_items` (later menu edits don't rewrite history), and money is integer cents. Tax is 8.25% (`TAX_BPS`), rounded half up. Quantities are 1–20, duplicate lines are merged, unavailable or unknown items are rejected with 422.

**Status machine.** One table, `FLOW`, defines legal moves: placed→preparing|cancelled, preparing→ready|cancelled, ready→delivered; delivered and cancelled are final. Illegal moves return 409 with the allowed options. The update is `UPDATE … WHERE id=? AND status=?`, so two staff members acting at once can't both win; the loser gets 409. A `CHECK` constraint on the column backs this up at the database level.

**Chatbot.** `chat.py` is a pure function: (message, cart, menu) → (reply, cart, confirm?). It matches menu names and aliases (longest first, optional plural), reads the quantity word before each match, and treats a “no/remove” word before an item as removal. The cart lives in the browser and is sent with each message, so the server stays stateless. The bot never prices anything; on “confirm” the server runs the same `create_order` as the normal checkout, so the chatbot cannot bypass any validation. An LLM could replace `handle` without touching the rest, as long as it returns the same shape.

**Auth.** Optional per the brief: staff endpoints require a shared token (`X-Staff-Token`, constant-time compare). Customers are anonymous.

**Known limits.**
- Order ids are sequential and `GET /api/orders/<id>` is public, so anyone can view any order's items and name. Production would use unguessable order tokens.
- The shared staff token is a stand-in for real accounts and sessions.
- The kitchen board polls every 4 seconds; SSE or websockets would be the next step.
- SQLite suits one restaurant; multiple servers would need Postgres.
- No menu-management UI (edit the `menu_items` table); no payments.
- The chatbot handles common phrasings, not arbitrary language (“two pizzas” asks nothing; it just says it didn't catch an item).
