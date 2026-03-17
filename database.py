import os
import logging
from datetime import date, datetime
import pytz
from supabase import create_client, Client

logger = logging.getLogger(__name__)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

_supabase: Client = None


def get_client() -> Client:
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(url, key)
    return _supabase


def get_moscow_date() -> str:
    """Текущая дата по Москве в формате YYYY-MM-DD"""
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")


# ============================================================
# Пользователи
# ============================================================

def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> dict:
    """Получить пользователя или создать, если не существует"""
    try:
        sb = get_client()
        result = sb.table("users").select("*").eq("telegram_id", telegram_id).execute()

        if result.data:
            user = result.data[0]
            # Обновить имя если изменилось
            if username and user.get("username") != username:
                sb.table("users").update({"username": username, "first_name": first_name}).eq(
                    "telegram_id", telegram_id
                ).execute()
                user["username"] = username
                user["first_name"] = first_name
            return user
        else:
            # Создать нового пользователя
            new_user = {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "requests_left": 0,
                "subscription_plan": None,
                "card_of_day_date": None,
                "card_of_day_card": None,
                "card_of_day_pending": None,
                "created_at": datetime.now(MOSCOW_TZ).isoformat(),
            }
            result = sb.table("users").insert(new_user).execute()
            return result.data[0] if result.data else new_user
    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        raise


def has_active_subscription(telegram_id: int) -> bool:
    """Проверить наличие активной подписки (остаток запросов > 0)"""
    try:
        sb = get_client()
        result = sb.table("users").select("requests_left").eq("telegram_id", telegram_id).execute()
        if result.data:
            return result.data[0].get("requests_left", 0) > 0
        return False
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False


def get_requests_left(telegram_id: int) -> int:
    """Получить количество оставшихся запросов"""
    try:
        sb = get_client()
        result = sb.table("users").select("requests_left").eq("telegram_id", telegram_id).execute()
        if result.data:
            return result.data[0].get("requests_left", 0)
        return 0
    except Exception as e:
        logger.error(f"Error getting requests_left: {e}")
        return 0


def use_request(telegram_id: int) -> bool:
    """Использовать один запрос (декремент). Возвращает True если успешно."""
    try:
        sb = get_client()
        result = sb.table("users").select("requests_left").eq("telegram_id", telegram_id).execute()
        if not result.data:
            return False
        current = result.data[0].get("requests_left", 0)
        if current <= 0:
            return False
        sb.table("users").update({"requests_left": current - 1}).eq(
            "telegram_id", telegram_id
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Error using request: {e}")
        return False


def add_subscription(telegram_id: int, requests_count: int, plan_name: str) -> bool:
    """Добавить запросы подписки пользователю"""
    try:
        sb = get_client()
        result = sb.table("users").select("requests_left").eq("telegram_id", telegram_id).execute()
        if not result.data:
            return False
        current = result.data[0].get("requests_left", 0)
        sb.table("users").update({
            "requests_left": current + requests_count,
            "subscription_plan": plan_name
        }).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error adding subscription: {e}")
        return False


# ============================================================
# Карта дня
# ============================================================

def get_card_of_day_info(telegram_id: int) -> dict:
    """Получить информацию о карте дня пользователя"""
    try:
        sb = get_client()
        result = sb.table("users").select(
            "card_of_day_date, card_of_day_card, card_of_day_pending"
        ).eq("telegram_id", telegram_id).execute()
        if result.data:
            return result.data[0]
        return {}
    except Exception as e:
        logger.error(f"Error getting card of day: {e}")
        return {}


def set_card_of_day_pending(telegram_id: int, pending_cards: list) -> bool:
    """Сохранить три предложенные карты (пользователь ещё не выбрал)"""
    try:
        sb = get_client()
        today = get_moscow_date()
        sb.table("users").update({
            "card_of_day_date": today,
            "card_of_day_card": None,
            "card_of_day_pending": pending_cards,
        }).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error setting pending cards: {e}")
        return False


def choose_card_of_day(telegram_id: int, card: dict) -> bool:
    """Пользователь выбрал карту"""
    try:
        sb = get_client()
        today = get_moscow_date()
        sb.table("users").update({
            "card_of_day_date": today,
            "card_of_day_card": card["name"],
            "card_of_day_pending": None,
        }).eq("telegram_id", telegram_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error choosing card: {e}")
        return False


def already_picked_card_today(telegram_id: int) -> bool:
    """Проверить, выбирал ли пользователь карту сегодня"""
    try:
        info = get_card_of_day_info(telegram_id)
        today = get_moscow_date()
        return (
            info.get("card_of_day_date") == today and
            info.get("card_of_day_card") is not None
        )
    except Exception as e:
        logger.error(f"Error checking card pick: {e}")
        return False


def already_started_card_today(telegram_id: int) -> bool:
    """Проверить, начинал ли пользователь выбор карты сегодня"""
    try:
        info = get_card_of_day_info(telegram_id)
        today = get_moscow_date()
        return (
            info.get("card_of_day_date") == today and
            info.get("card_of_day_pending") is not None
        )
    except Exception as e:
        logger.error(f"Error checking card start: {e}")
        return False


def get_pending_cards(telegram_id: int) -> list:
    """Получить список предложенных карт"""
    try:
        info = get_card_of_day_info(telegram_id)
        return info.get("card_of_day_pending") or []
    except Exception as e:
        logger.error(f"Error getting pending cards: {e}")
        return []


# ============================================================
# Для уведомлений
# ============================================================

def get_all_user_ids() -> list:
    """Получить список всех telegram_id пользователей"""
    try:
        sb = get_client()
        result = sb.table("users").select("telegram_id").execute()
        return [row["telegram_id"] for row in result.data] if result.data else []
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return []


def reset_all_card_of_day() -> bool:
    """Сбросить карты дня для всех (вызывается в 12:00 по Москве)"""
    try:
        sb = get_client()
        sb.table("users").update({
            "card_of_day_pending": None,
        }).neq("telegram_id", 0).execute()
        return True
    except Exception as e:
        logger.error(f"Error resetting cards: {e}")
        return False
