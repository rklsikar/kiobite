import os
import json
import hmac
import hashlib
import secrets
import datetime
import requests
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from sqlalchemy import create_engine, Column, String, Integer, Numeric, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from dotenv import load_dotenv
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
# --- LOAD ENV ---
load_dotenv()

# --- CONFIG ---
WHATSAPP_PHONE_NUMBER_ID = "1325736767285456"
WHATSAPP_ACCESS_TOKEN = "EAAWrtPL1P0gBSoUt9ESoDevvTZCOgDaWolxYD6f16me0iikEehZCZAqY9uBOYmgZAfsBxeMVRiouDKlfrpVsAxDdFZCeTF0GrSwOVuEChQZAbgWqYiaYjs52hCd5aCRht0huhUgo0MwaYNi3aiQKofR1RSd1MDbTavzVK4qi98MZA6Vjh0m5exZADkAGSCcoHjpWowZDZD"
WHATSAPP_APP_SECRET = "6e8e62de67728b8040b81e8420810467"
VERIFY_TOKEN = "KIOBITE_SECURE_TOKEN_2026"
PAYMENT_BASE_URL = "https://kiobite.onrender.com"
GRAPH_API_VERSION = "v20.0"

# --- DATABASE ---
DATABASE_URL = "sqlite:///kiobite.db"
templates = Jinja2Templates(directory="templates")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- PRODUCT CATALOG ---
PRODUCT_CATALOG = {
    "1": {"name": "Chana Sattu Hydration Pack", "price": 40.00},
    "2": {"name": "High-Protein Super Oats", "price": 60.00},
    "3": {"name": "Campa Cola 200ml", "price": 10.00},
    "4": {"name": "Snactac Biscuits", "price": 10.00},
    "5": {"name": "Lahori Zeera 200ml", "price": 10.00},
    "6": {"name": "Independence Oil 500ml", "price": 200.00},
}

# --- APP INITIALIZATION ---
app = FastAPI(title="KioBite Tech Engine")


# --- DATABASE MODELS ---
class User(Base):
    __tablename__ = "users"
    phone_number = Column(String(15), primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Cart(Base):
    __tablename__ = "carts"
    phone_number = Column(String(15), primary_key=True, index=True)
    items_json = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    order_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    phone_number = Column(String(15), index=True)
    kiosk_id = Column(String(50), nullable=False, default="KIOSK_01")
    items_json = Column(JSON, nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    payment_status = Column(String(20), default="PENDING")
    pickup_code = Column(String(6), unique=True, index=True)
    payment_link = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- WHATSAPP SEND ---
def send_whatsapp_message(recipient_phone: str, text_body: str):
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text_body}
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"[OK] Meta Send API Response: {response.json()}")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Sending message failed: {e}")
        return None


# --- SIGNATURE VERIFICATION ---
def verify_signature(payload: bytes, signature: str) -> bool:
    if not WHATSAPP_APP_SECRET:
        print("[WARN] WHATSAPP_APP_SECRET not set - skipping signature verification")
        return True
    if not signature:
        return False
    expected = hmac.new(
        WHATSAPP_APP_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


# --- HELPERS ---
def get_or_create_cart(db: Session, phone: str) -> Cart:
    cart = db.query(Cart).filter(Cart.phone_number == phone).first()
    if not cart:
        cart = Cart(phone_number=phone, items_json={})
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart


def generate_pickup_code() -> str:
    return secrets.token_hex(3).upper()


def format_menu() -> str:
    lines = ["🚀 Welcome to KioBite Express Pickup!", "Reply with the item number to add to cart:", ""]
    for pid, item in PRODUCT_CATALOG.items():
        lines.append(f"{pid}. {item['name']} - Rs.{item['price']:.0f}")
    lines.append("")
    lines.append("Reply *confirm* to place order.")
    lines.append("Reply *cancel* to clear cart.")
    lines.append("Reply *status* to see recent orders.")
    return "\n".join(lines)


def format_cart(cart: Cart) -> str:
    items = cart.items_json or {}
    if not items:
        return "Your cart is empty."
    lines = ["🛒 Your cart:"]
    total = 0.0
    for pid, qty in items.items():
        if pid in PRODUCT_CATALOG:
            item = PRODUCT_CATALOG[pid]
            subtotal = item["price"] * qty
            total += subtotal
            lines.append(f"  {item['name']} x{qty} = Rs.{subtotal:.0f}")
    lines.append(f"Total: Rs.{total:.2f}")
    return "\n".join(lines)


# --- WEBHOOK VERIFICATION ---
@app.get("/webhook")
def verify_meta_webhook(request: Request):
    params = request.query_params
    headers = {"ngrok-skip-browser-warning": "true", "Bypass-Tunnel-Reminder": "true"}
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        print("[OK] Webhook verified by Meta")
        return Response(content=params.get("hub.challenge"), headers=headers)
    print("[ERROR] Webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification Token Invalid")


# --- WEBHOOK HANDLER ---
@app.post("/webhook")
async def handle_incoming_whatsapp(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(body)
    print(f"[IN] Received Webhook Payload: {json.dumps(payload)}")

    try:
        entry = payload["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        # Ignore status updates (delivery/read receipts)
        if "statuses" in value:
            return {"status": "IGNORED_STATUS"}

        if "messages" not in value:
            return {"status": "IGNORED_NO_MESSAGE"}

        message = value["messages"][0]
        customer_phone = message["from"]

        # Only handle text messages
        if message.get("type") != "text":
            send_whatsapp_message(customer_phone, "Please send a text message. Reply *menu* to see options.")
            return {"status": "NON_TEXT"}

        user_msg_body = message["text"]["body"].strip().lower()

        # Register user
        if not db.query(User).filter(User.phone_number == customer_phone).first():
            db.add(User(phone_number=customer_phone))
            db.commit()

        cart = get_or_create_cart(db, customer_phone)

        # --- HANDLE COMMANDS ---
        if user_msg_body in ["hi", "hello", "menu", "kiobite", "start"]:
            send_whatsapp_message(customer_phone, format_menu())

        elif user_msg_body in PRODUCT_CATALOG:
            pid = user_msg_body
            item = PRODUCT_CATALOG[pid]
            items = cart.items_json or {}
            items[pid] = items.get(pid, 0) + 1
            cart.items_json = items
            db.commit()
            db.refresh(cart)
            send_whatsapp_message(
                customer_phone,
                f"✅ Added {item['name']} (Rs.{item['price']:.0f}) to cart.\n\n"
                f"{format_cart(cart)}\n\n"
                f"Reply *confirm* to place order, *menu* to add more, or *cancel* to clear."
            )

        elif user_msg_body == "cart":
            send_whatsapp_message(customer_phone, format_cart(cart))

        elif user_msg_body == "confirm":
            items = cart.items_json or {}
            if not items:
                send_whatsapp_message(customer_phone, "🛒 Your cart is empty. Reply *menu* to add items.")
                return {"status": "EMPTY_CART"}

            total = sum(
                PRODUCT_CATALOG[pid]["price"] * qty
                for pid, qty in items.items()
                if pid in PRODUCT_CATALOG
            )
            pickup_code = generate_pickup_code()
            order = Order(
                phone_number=customer_phone,
                items_json=items,
                total_amount=total,
                pickup_code=pickup_code,
                payment_status="PENDING"
            )
            db.add(order)
            db.commit()
            db.refresh(order)

            # Clear cart
            cart.items_json = {}
            db.commit()

            payment_link = f"{PAYMENT_BASE_URL}/payment/{order.order_id}"
            order.payment_link = payment_link
            db.commit()

            msg = (
                f"🧾 Order #{order.order_id} created!\n\n"
                f"Total: Rs.{total:.2f}\n"
                f"Pickup Code (after payment): *{pickup_code}*\n\n"
                f"💳 Pay here: {payment_link}\n\n"
                f"After payment, you will receive a confirmation."
            )
            send_whatsapp_message(customer_phone, msg)

        elif user_msg_body == "cancel":
            cart.items_json = {}
            db.commit()
            send_whatsapp_message(customer_phone, "🗑️ Cart cleared. Reply *menu* to start again.")

        elif user_msg_body == "status":
            orders = (
                db.query(Order)
                .filter(Order.phone_number == customer_phone)
                .order_by(Order.created_at.desc())
                .limit(3)
                .all()
            )
            if not orders:
                send_whatsapp_message(customer_phone, "No orders found. Reply *menu* to place one.")
            else:
                lines = ["📦 Your recent orders:"]
                for o in orders:
                    lines.append(f"#{o.order_id} - Rs.{o.total_amount} - {o.payment_status} - Pickup: {o.pickup_code}")
                send_whatsapp_message(customer_phone, "\n".join(lines))

        else:
            send_whatsapp_message(customer_phone, "🤖 I didn't understand. Reply *menu* to see options.")

        return {"status": "PROCESSED"}

    except Exception as e:
        print(f"[ERROR] Parsing Error: {str(e)}")
        return {"status": "IGNORED", "reason": str(e)}


# --- ROOT POST (NGROK BYPASS) ---
@app.post("/")
async def handle_root_post(request: Request, db: Session = Depends(get_db)):
    headers = {"ngrok-skip-browser-warning": "true", "Bypass-Tunnel-Reminder": "true"}
    response_data = await handle_incoming_whatsapp(request, db)
    return Response(content=json.dumps(response_data), media_type="application/json", headers=headers)


# --- MOCK PAYMENT ENDPOINT ---
@app.get("/payment/{order_id}")
async def mock_payment(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_status == "PAID":
        return {"status": "ALREADY_PAID", "pickup_code": order.pickup_code}

    order.payment_status = "PAID"
    db.commit()

    msg = (
        f"✅ Payment received for Order #{order.order_id}!\n\n"
        f"Your pickup code is: *{order.pickup_code}*\n\n"
        f"Show this code at the KioBite kiosk to collect your items."
    )
    send_whatsapp_message(order.phone_number, msg)

    return {
        "status": "PAID",
        "order_id": order.order_id,
        "pickup_code": order.pickup_code,
        "message": "Payment successful. Show this code at the kiosk."
    }


# --- ADMIN: LIST ALL ORDERS ---
@app.get("/orders")
def list_orders(db: Session = Depends(get_db)):
    orders = db.query(Order).order_by(Order.created_at.desc()).limit(50).all()
    return [
        {
            "order_id": o.order_id,
            "phone": o.phone_number,
            "items": o.items_json,
            "total": float(o.total_amount),
            "status": o.payment_status,
            "pickup_code": o.pickup_code,
            "created_at": o.created_at.isoformat() if o.created_at else None
        }
        for o in orders
    ]
# --- ADMIN DASHBOARD ---
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
        return templates.TemplateResponse(request=request, name="dashboard.html")

# --- HEALTH CHECK ---
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
