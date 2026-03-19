import os
import logging
from datetime import datetime
import pytz
from supabase import create_client, Client

logger = logging.getLogger(__name__)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
_sb: Client = None

def get_client() -> Client:
    global _sb
    if _sb is None:
        url = os.getenv("SUPABASE_URL"); key = os.getenv("SUPABASE_KEY")
        if not url or not key: raise ValueError("SUPABASE_URL / SUPABASE_KEY не заданы")
        _sb = create_client(url, key)
    return _sb

def get_moscow_date() -> str:
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")

# ── Пользователи ─────────────────────────────────────────────────────

def get_or_create_user(telegram_id, username=None, first_name=None):
    try:
        sb = get_client()
        r = sb.table("users").select("*").eq("telegram_id", telegram_id).execute()
        if r.data:
            u = r.data[0]
            if username and u.get("username") != username:
                sb.table("users").update({"username": username, "first_name": first_name}).eq("telegram_id", telegram_id).execute()
            return u
        nu = {"telegram_id": telegram_id, "username": username, "first_name": first_name,
              "requests_left": 0, "subscription_plan": None,
              "card_of_day_date": None, "card_of_day_card": None, "card_of_day_pending": None,
              "created_at": datetime.now(MOSCOW_TZ).isoformat()}
        r = sb.table("users").insert(nu).execute()
        return r.data[0] if r.data else nu
    except Exception as e: logger.error(f"get_or_create_user: {e}"); raise

def has_active_subscription(telegram_id) -> bool:
    try:
        r = get_client().table("users").select("requests_left").eq("telegram_id", telegram_id).execute()
        return r.data[0].get("requests_left", 0) > 0 if r.data else False
    except Exception as e: logger.error(e); return False

def get_requests_left(telegram_id) -> int:
    try:
        r = get_client().table("users").select("requests_left").eq("telegram_id", telegram_id).execute()
        return r.data[0].get("requests_left", 0) if r.data else 0
    except Exception as e: logger.error(e); return 0

def use_request(telegram_id) -> bool:
    try:
        sb = get_client()
        r = sb.table("users").select("requests_left").eq("telegram_id", telegram_id).execute()
        if not r.data: return False
        cur = r.data[0].get("requests_left", 0)
        if cur <= 0: return False
        sb.table("users").update({"requests_left": cur - 1}).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e: logger.error(e); return False

def add_subscription(telegram_id, requests_count, plan_name) -> bool:
    try:
        sb = get_client()
        r = sb.table("users").select("requests_left").eq("telegram_id", telegram_id).execute()
        if not r.data: return False
        cur = r.data[0].get("requests_left", 0)
        sb.table("users").update({"requests_left": cur + requests_count, "subscription_plan": plan_name}).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e: logger.error(e); return False

# ── Карта дня ────────────────────────────────────────────────────────

def get_card_of_day_info(telegram_id):
    try:
        r = get_client().table("users").select("card_of_day_date,card_of_day_card,card_of_day_pending").eq("telegram_id", telegram_id).execute()
        return r.data[0] if r.data else {}
    except Exception as e: logger.error(e); return {}

def set_card_of_day_pending(telegram_id, pending_cards) -> bool:
    try:
        get_client().table("users").update({"card_of_day_date": get_moscow_date(), "card_of_day_card": None, "card_of_day_pending": pending_cards}).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e: logger.error(e); return False

def choose_card_of_day(telegram_id, card) -> bool:
    try:
        get_client().table("users").update({"card_of_day_date": get_moscow_date(), "card_of_day_card": card["name"], "card_of_day_pending": None}).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e: logger.error(e); return False

def already_picked_card_today(telegram_id) -> bool:
    i = get_card_of_day_info(telegram_id)
    return i.get("card_of_day_date") == get_moscow_date() and i.get("card_of_day_card") is not None

def already_started_card_today(telegram_id) -> bool:
    i = get_card_of_day_info(telegram_id)
    return i.get("card_of_day_date") == get_moscow_date() and i.get("card_of_day_pending") is not None

def get_pending_cards(telegram_id) -> list:
    return get_card_of_day_info(telegram_id).get("card_of_day_pending") or []

def get_all_user_ids() -> list:
    try:
        r = get_client().table("users").select("telegram_id").execute()
        return [row["telegram_id"] for row in r.data] if r.data else []
    except Exception as e: logger.error(e); return []

# ── ЮKassa: pending payments ─────────────────────────────────────────

def save_pending_payment(payment_id: str, telegram_id: int, plan_label: str) -> bool:
    try:
        get_client().table("pending_payments").insert({
            "payment_id": payment_id, "telegram_id": telegram_id,
            "plan_label": plan_label, "processed": False,
            "created_at": datetime.now(MOSCOW_TZ).isoformat(),
        }).execute()
        return True
    except Exception as e: logger.error(f"save_pending_payment: {e}"); return False

def get_pending_payment(payment_id: str) -> dict:
    try:
        r = get_client().table("pending_payments").select("*").eq("payment_id", payment_id).execute()
        return r.data[0] if r.data else None
    except Exception as e: logger.error(f"get_pending_payment: {e}"); return None

def is_payment_processed(payment_id: str) -> bool:
    try:
        r = get_client().table("pending_payments").select("processed").eq("payment_id", payment_id).execute()
        return r.data[0].get("processed", False) if r.data else False
    except Exception as e: logger.error(f"is_payment_processed: {e}"); return False

def mark_payment_processed(payment_id: str) -> bool:
    try:
        get_client().table("pending_payments").update({"processed": True}).eq("payment_id", payment_id).execute()
        return True
    except Exception as e: logger.error(f"mark_payment_processed: {e}"); return False
