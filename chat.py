"""Rule-based ordering chatbot. Pure logic: no I/O, no database access.

handle(message, cart, menu) -> {"reply": str, "cart": {id: qty}, "confirm": bool}
The server remains the authority: it re-validates the cart and prices the order.
"""
import re

NUMS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
NUMS.update({"a": 1, "an": 1, "another": 1})
QTY = re.compile(r"\b(\d+|" + "|".join(NUMS) + r")\b")
CONFIRM = re.compile(r"\b(yes|yep|yeah|confirm|checkout|check out|place (it|the order|my order)|that'?s (all|it)|go ahead)\b")
CLEAR = re.compile(r"\b(clear|start over|empty|cancel|reset)\b")
REMOVE = re.compile(r"\b(remove|delete|drop|without|no|cancel|take off)\b")
MENU_Q = re.compile(r"\b(menu|options|what do you have|what('s| is) available)\b")
MAX_QTY = 20


def money(c):
    return f"${c / 100:.2f}"


def _summary(cart, menu):
    lines = ", ".join(f"{q}× {menu[i]['name']}" for i, q in cart.items())
    sub = sum(menu[i]["price_cents"] * q for i, q in cart.items())
    return f"Your order: {lines}. Subtotal {money(sub)} (tax added at checkout). Say “confirm” to place it."


def handle(message, cart, menu):
    text = message.lower()
    cart = {i: q for i, q in cart.items() if i in menu}
    alias_to_id = {}
    for i, m in menu.items():
        for a in [m["name"]] + (m.get("aliases") or "").split(","):
            if a.strip():
                alias_to_id[a.strip().lower()] = i
    matches = []
    if alias_to_id:
        names = sorted(alias_to_id, key=len, reverse=True)  # longest alias wins
        pat = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")(?:e?s)?\b")
        matches = list(pat.finditer(text))

    if matches:
        notes, prev = [], 0
        for m in matches:
            seg = text[prev:m.start()]
            prev = m.end()
            item = menu[alias_to_id[m.group(1)]]
            nums = QTY.findall(seg)
            q = 1
            if nums:
                q = int(nums[-1]) if nums[-1].isdigit() else NUMS[nums[-1]]
            if REMOVE.search(seg):
                if cart.pop(item["id"], None) is not None:
                    notes.append(f"removed {item['name']}")
                continue
            if q < 1:
                continue
            new = cart.get(item["id"], 0) + q
            if new > MAX_QTY:
                new = MAX_QTY
                notes.append(f"capped {item['name']} at {MAX_QTY}")
            else:
                notes.append(f"added {q}× {item['name']}")
            cart[item["id"]] = new
        head = ("Done: " + "; ".join(notes) + ". ") if notes else ""
        tail = _summary(cart, menu) if cart else "Your cart is empty."
        return {"reply": head + tail, "cart": cart, "confirm": False}

    if CONFIRM.search(text):
        if not cart:
            return {"reply": "Your cart is empty. Tell me what you'd like first.", "cart": cart, "confirm": False}
        return {"reply": "", "cart": cart, "confirm": True}
    if CLEAR.search(text):
        return {"reply": "Cleared. What would you like instead?", "cart": {}, "confirm": False}
    if MENU_Q.search(text):
        return {"reply": "We have: " + ", ".join(m["name"] for m in menu.values()) + ".", "cart": cart, "confirm": False}
    hint = "Try “two margherita pizzas and a cola”, or ask for the menu."
    return {"reply": "I didn't catch a menu item. " + hint, "cart": cart, "confirm": False}
