import os
import logging
import uuid
import pytz
from aiohttp import web
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, PreCheckoutQueryHandler, filters, ContextTypes,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv
from yookassa import Configuration, Payment as YKPayment
import database as db
import groq_client
from tarot_cards import SPREADS, draw_cards, format_cards_text
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

logging.basicConfig(format="%(asctime)s — %(name)s — %(levelname)s — %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN        = os.getenv("TELEGRAM_TOKEN")
MOSCOW_TZ    = pytz.timezone("Europe/Moscow")
YK_SHOP_ID   = os.getenv("YOOKASSA_SHOP_ID", "")
YK_SECRET    = os.getenv("YOOKASSA_SECRET_KEY", "")
WEBHOOK_PORT = int(os.getenv("PORT", 8080))

if YK_SHOP_ID and YK_SECRET:
    Configuration.account_id = YK_SHOP_ID
    Configuration.secret_key  = YK_SECRET

STATE_IDLE            = "idle"
STATE_ASK_QUESTION    = "ask_question"
STATE_SPREAD_QUESTION = "spread_question"

# ── Тарифы ЮKassa ────────────────────────────────────────────────────
YK_PLANS = [
    {"label": "yk_99",  "name": "🌙 Старт",       "price":  99, "requests":   3, "desc": "3 расклада"},
    {"label": "yk_249", "name": "⭐ Популярный",  "price": 249, "requests":  10, "desc": "10 раскладов"},
    {"label": "yk_499", "name": "🔥 Продвинутый", "price": 499, "requests":  25, "desc": "25 раскладов"},
    {"label": "yk_999", "name": "👑 VIP",          "price": 999, "requests": 100, "desc": "100 раскладов"},
]
YK_PLANS_BY_LABEL = {p["label"]: p for p in YK_PLANS}

# ── Тарифы Telegram Stars ─────────────────────────────────────────────
STARS_PLANS = [
    {"label": "stars_1",  "name": "🌙 Пробный",     "stars":  1, "requests":  100, "desc": "Попробовать"},
    {"label": "stars_5",  "name": "⭐ Популярный",  "stars":  5, "requests":  500, "desc": "Лучший выбор"},
    {"label": "stars_15", "name": "🔥 Продвинутый", "stars": 15, "requests": 1500, "desc": "Серьёзная работа"},
    {"label": "stars_50", "name": "👑 VIP",          "stars": 50, "requests": 5000, "desc": "Без ограничений"},
]
STARS_PLANS_BY_LABEL = {p["label"]: p for p in STARS_PLANS}

# ─────────────────────────── клавиатуры ──────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔮 Задать вопрос",     callback_data="ask_question")],
        [InlineKeyboardButton("🎴 Расклады",          callback_data="spreads")],
        [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
        [InlineKeyboardButton("🌅 Карта дня",         callback_data="card_of_day")],
        [InlineKeyboardButton("ℹ️ Информация",         callback_data="info")],
    ])

def back_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]])
def cancel_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="main_menu")]])

def spreads_kb():
    b = [[InlineKeyboardButton(s["name"], callback_data=f"spread_{k}")] for k, s in SPREADS.items()]
    b.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(b)

def subscribe_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить картой  (ЮKassa)", callback_data="sub_yookassa")],
        [InlineKeyboardButton("⭐ Оплатить Telegram Stars",   callback_data="sub_stars")],
        [InlineKeyboardButton("🏠 Главное меню",             callback_data="main_menu")],
    ])

def yk_plans_kb():
    b = [[InlineKeyboardButton(f"{p['name']} — {p['price']}₽  ({p['desc']})", callback_data=f"buy_yk_{p['label']}")] for p in YK_PLANS]
    b += [[InlineKeyboardButton("◀️ Назад", callback_data="subscribe")]]
    return InlineKeyboardMarkup(b)

def stars_plans_kb():
    b = [[InlineKeyboardButton(f"⭐ {p['stars']} звезд → {p['requests']} запросов  ({p['name']})", callback_data=f"buy_stars_{p['label']}")] for p in STARS_PLANS]
    b += [[InlineKeyboardButton("◀️ Назад", callback_data="subscribe")]]
    return InlineKeyboardMarkup(b)

def cod_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🂠 Карта 1", callback_data="pick_card_0"),
         InlineKeyboardButton("🂠 Карта 2", callback_data="pick_card_1"),
         InlineKeyboardButton("🂠 Карта 3", callback_data="pick_card_2")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
    ])

# ─────────────────────────── /start ──────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_or_create_user(telegram_id=u.id, username=u.username, first_name=u.first_name)
    context.user_data["state"] = STATE_IDLE
    await update.message.reply_text(
        f"✨ *Добро пожаловать в Таро-бота, {u.first_name}!* ✨\n\n"
        "Я — ваш персональный проводник в мире Таро.\n\n"
        "🔮 *Что я умею:*\n"
        "• Отвечать на личные вопросы через расклады\n"
        "• Делать 10 видов тематических раскладов\n"
        "• Каждый день дарить карту дня — бесплатно!\n\n"
        "💳 *Оплата:* картой (ЮKassa) или Telegram Stars ⭐\n\n"
        "Выберите действие 👇",
        reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN,
    )

# ─────────────────────────── callback handler ─────────────────────────

async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    uid = q.from_user.id

    if d == "main_menu":
        context.user_data.update({"state": STATE_IDLE})
        context.user_data.pop("current_spread", None)
        await q.edit_message_text("🏠 *Главное меню*\n\nВыберите действие:", reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

    elif d == "ask_question":
        if not db.has_active_subscription(uid):
            await q.edit_message_text(
                "🔒 *Нет активной подписки*\n\nОформите подписку, чтобы задавать вопросы.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]),
                parse_mode=ParseMode.MARKDOWN)
            return
        context.user_data["state"] = STATE_ASK_QUESTION
        await q.edit_message_text(
            f"🔮 *Задайте ваш вопрос*\n\nОсталось запросов: *{db.get_requests_left(uid)}*\n\nНапишите ваш вопрос:",
            reply_markup=cancel_kb(), parse_mode=ParseMode.MARKDOWN)

    elif d == "spreads":
        context.user_data["state"] = STATE_IDLE
        await q.edit_message_text("🎴 *Расклады Таро*\n\nВыберите тему:", reply_markup=spreads_kb(), parse_mode=ParseMode.MARKDOWN)

    elif d.startswith("spread_"):
        key = d.replace("spread_", "")
        if key not in SPREADS:
            await q.edit_message_text("Расклад не найден.", reply_markup=back_kb()); return
        s = SPREADS[key]; context.user_data["current_spread"] = key
        await q.edit_message_text(
            f"{s['emoji']} *{s['name']}*\n\n_{s['full_desc']}_\n\n{s['how_to_ask']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎴 Начать расклад", callback_data=f"start_spread_{key}")],
                [InlineKeyboardButton("◀️ К раскладам", callback_data="spreads")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ]), parse_mode=ParseMode.MARKDOWN)

    elif d.startswith("start_spread_"):
        key = d.replace("start_spread_", "")
        if key not in SPREADS:
            await q.edit_message_text("Расклад не найден.", reply_markup=back_kb()); return
        if not db.has_active_subscription(uid):
            await q.edit_message_text(
                "🔒 *Нет активной подписки*\n\nДля расклада нужна подписка.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Оформить", callback_data="subscribe")],[InlineKeyboardButton("◀️ Назад", callback_data=f"spread_{key}")]]),
                parse_mode=ParseMode.MARKDOWN); return
        context.user_data["state"] = STATE_SPREAD_QUESTION
        context.user_data["current_spread"] = key
        await q.edit_message_text(
            f"🎴 *{SPREADS[key]['name']}*\n\nОсталось: *{db.get_requests_left(uid)}* запросов\n\nВведите вопрос:",
            reply_markup=cancel_kb(), parse_mode=ParseMode.MARKDOWN)

    # ── Подписка ───────────────────────────────────────────────────────
    elif d == "subscribe":
        rl = db.get_requests_left(uid)
        await q.edit_message_text(
            f"💳 *Оформление подписки*\n\nВаш баланс: *{rl} запросов*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Выберите удобный способ оплаты:\n\n"
            "💳 *ЮKassa* — Visa, МИР, SberPay, SBP и др.\n"
            "⭐ *Telegram Stars* — внутренняя валюта Telegram",
            reply_markup=subscribe_main_kb(), parse_mode=ParseMode.MARKDOWN)

    elif d == "sub_yookassa":
        pt = "\n\n".join([f"*{p['name']}*\n{p['price']}₽ → {p['desc']}" for p in YK_PLANS])
        await q.edit_message_text(
            f"💳 *Оплата картой — ЮKassa*\n\n━━━━━━━━━━━━━━━━━━━━\n{pt}\n\n━━━━━━━━━━━━━━━━━━━━\n"
            "После оплаты запросы зачислятся *автоматически*.",
            reply_markup=yk_plans_kb(), parse_mode=ParseMode.MARKDOWN)

    elif d.startswith("buy_yk_"):
        await handle_yk_payment(q, uid, d.replace("buy_yk_", ""))

    elif d == "sub_stars":
        pt = "\n\n".join([f"*{p['name']}* — {p['stars']} ⭐ → {p['requests']} запросов\n_{p['desc']}_" for p in STARS_PLANS])
        await q.edit_message_text(
            f"⭐ *Оплата Telegram Stars*\n\n━━━━━━━━━━━━━━━━━━━━\n💫 1 звезда = 100 запросов\n\n{pt}\n\n━━━━━━━━━━━━━━━━━━━━\nЗапросы накапливаются и не сгорают.",
            reply_markup=stars_plans_kb(), parse_mode=ParseMode.MARKDOWN)

    elif d.startswith("buy_stars_"):
        plan = STARS_PLANS_BY_LABEL.get(d.replace("buy_stars_", ""))
        if not plan: await q.answer("План не найден", show_alert=True); return
        await q.message.reply_invoice(
            title=f"{plan['name']} — {plan['requests']} запросов",
            description=f"Таро-бот: {plan['requests']} запросов. 1 ⭐ = 100 запросов.",
            payload=plan["label"], provider_token="", currency="XTR",
            prices=[LabeledPrice(label=f"{plan['requests']} запросов", amount=plan["stars"])],
        )

    # ── Карта дня ──────────────────────────────────────────────────────
    elif d == "card_of_day":
        await handle_card_of_day(q, uid)
    elif d.startswith("pick_card_"):
        await handle_pick_card(q, uid, int(d.replace("pick_card_", "")))

    elif d == "info":
        await handle_info(q)

# ─────────────────────────── ЮKassa: создание платежа ────────────────

async def handle_yk_payment(q, uid: int, plan_label: str):
    plan = YK_PLANS_BY_LABEL.get(plan_label)
    if not plan: await q.answer("План не найден", show_alert=True); return
    if not YK_SHOP_ID or not YK_SECRET:
        await q.edit_message_text(
            "⚠️ Оплата картой временно недоступна. Воспользуйтесь Telegram Stars.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Оплатить Stars", callback_data="sub_stars")],[InlineKeyboardButton("◀️ Назад", callback_data="subscribe")]]),
            parse_mode=ParseMode.MARKDOWN); return
    try:
        payment = YKPayment.create({
            "amount": {"value": f"{plan['price']}.00", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": f"https://t.me/{q.get_bot().username}",
            "capture": True,
            "description": f"Таро-бот: {plan['desc']} ({plan['name']})",
            "metadata": {"user_id": str(uid), "plan_label": plan_label},
        }, str(uuid.uuid4()))
        db.save_pending_payment(payment_id=payment.id, telegram_id=uid, plan_label=plan_label)
        pay_url = payment.confirmation.confirmation_url
        await q.edit_message_text(
            f"💳 *{plan['name']}*\n\nСумма: *{plan['price']} ₽*\nВы получите: *{plan['requests']} запросов*\n\n"
            "Нажмите кнопку, оплатите и вернитесь в бот.\nЗапросы зачислятся *автоматически* 🔮",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Перейти к оплате", url=pay_url)],
                [InlineKeyboardButton("◀️ Назад", callback_data="sub_yookassa")],
            ]), parse_mode=ParseMode.MARKDOWN)
        logger.info(f"YK payment created: {payment.id} user={uid} plan={plan_label}")
    except Exception as e:
        logger.error(f"YooKassa create error: {e}")
        await q.edit_message_text(
            "⚠️ Не удалось создать платёж. Попробуйте позже или оплатите Stars.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Stars", callback_data="sub_stars")],[InlineKeyboardButton("◀️ Назад", callback_data="subscribe")]]),
            parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────── ЮKassa webhook ──────────────────────────

async def yookassa_webhook(request: web.Request) -> web.Response:
    try: body = await request.json()
    except Exception: return web.Response(status=400, text="Bad JSON")

    event = body.get("event", "")
    obj   = body.get("object", {})
    logger.info(f"YK webhook: {event}  id={obj.get('id')}")

    if event != "payment.succeeded":
        return web.Response(status=200, text="OK")

    payment_id = obj.get("id")
    meta       = obj.get("metadata", {})
    uid        = int(meta.get("user_id", 0))
    plan_label = meta.get("plan_label", "")

    if not uid or not plan_label:
        row = db.get_pending_payment(payment_id)
        if row: uid, plan_label = row["telegram_id"], row["plan_label"]

    plan = YK_PLANS_BY_LABEL.get(plan_label)
    if not plan:
        logger.error(f"YK webhook: unknown plan {plan_label}"); return web.Response(status=200, text="OK")

    if db.is_payment_processed(payment_id):
        logger.info(f"YK webhook: {payment_id} already done"); return web.Response(status=200, text="OK")

    db.add_subscription(telegram_id=uid, requests_count=plan["requests"], plan_name=plan["name"])
    db.mark_payment_processed(payment_id)
    rl = db.get_requests_left(uid)
    logger.info(f"YK success: user={uid} +{plan['requests']} requests")

    bot_app: Application = request.app["bot_app"]
    try:
        await bot_app.bot.send_message(
            chat_id=uid,
            text=(
                f"✅ *Оплата прошла!*\n\n"
                f"💳 ЮKassa (карта)\n"
                f"🎁 Начислено: *{plan['requests']} запросов*\n"
                f"💼 Баланс: *{rl} запросов*\n\n"
                "Теперь вы можете делать расклады 🔮"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔮 Задать вопрос", callback_data="ask_question")],
                [InlineKeyboardButton("🎴 Расклады",      callback_data="spreads")],
                [InlineKeyboardButton("🏠 Главное меню",  callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e: logger.warning(f"Notify {uid}: {e}")
    return web.Response(status=200, text="OK")

# ─────────────────────────── Telegram Stars ──────────────────────────

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pq = update.pre_checkout_query
    plan = STARS_PLANS_BY_LABEL.get(pq.invoice_payload)
    await pq.answer(ok=bool(plan), error_message=None if plan else "Неизвестный план.")
    if plan: logger.info(f"Stars pre-checkout OK: user={pq.from_user.id} {plan['label']}")

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p   = update.message.successful_payment
    uid = update.effective_user.id
    plan = STARS_PLANS_BY_LABEL.get(p.invoice_payload)
    if not plan:
        await update.message.reply_text("⚠️ Оплата прошла, но план не распознан.", reply_markup=back_kb()); return
    db.add_subscription(telegram_id=uid, requests_count=plan["requests"], plan_name=plan["name"])
    rl = db.get_requests_left(uid)
    logger.info(f"Stars OK: user={uid} {p.total_amount}⭐ +{plan['requests']}")
    await update.message.reply_text(
        f"✅ *Оплата прошла!*\n\n⭐ Telegram Stars\n⭐ Списано: *{p.total_amount} звезд*\n"
        f"🎁 Начислено: *{plan['requests']} запросов*\n💼 Баланс: *{rl} запросов*\n\n"
        "Теперь вы можете делать расклады 🔮",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔮 Задать вопрос", callback_data="ask_question")],
            [InlineKeyboardButton("🎴 Расклады",      callback_data="spreads")],
            [InlineKeyboardButton("🏠 Главное меню",  callback_data="main_menu")],
        ]), parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────── Карта дня ───────────────────────────────

async def handle_card_of_day(q, uid):
    if db.already_picked_card_today(uid):
        info = db.get_card_of_day_info(uid)
        await q.edit_message_text(
            f"🌅 *Карта дня*\n\nВы уже выбрали карту сегодня: *{info.get('card_of_day_card','?')}* 🃏\n\n"
            "Карта дня обновляется в *12:00 МСК*. Приходите завтра! ✨",
            reply_markup=back_kb(), parse_mode=ParseMode.MARKDOWN); return
    if db.already_started_card_today(uid):
        pending = db.get_pending_cards(uid)
        await q.edit_message_text(
            "🌅 *Карта дня*\n\nВыберите одну из трёх карт 🔮\n\n👇 *Выберите:*",
            reply_markup=cod_kb(), parse_mode=ParseMode.MARKDOWN); return
    pending = draw_cards(3)
    db.set_card_of_day_pending(uid, [{"name": c["name"], "element": c["element"], "keywords": c["keywords"]} for c in pending])
    await q.edit_message_text(
        "🌅 *Карта дня*\n\nТри закрытые карты. Прислушайтесь к интуиции и выберите одну 🔮\n\n👇 *Выберите:*",
        reply_markup=cod_kb(), parse_mode=ParseMode.MARKDOWN)

async def handle_pick_card(q, uid, idx):
    pending = db.get_pending_cards(uid)
    if not pending or idx >= len(pending):
        await q.edit_message_text("⚠️ Ошибка. Начните выбор заново.", reply_markup=back_kb()); return
    chosen = pending[idx]
    db.choose_card_of_day(uid, chosen)
    await q.edit_message_text(f"🎴 *Карта {idx+1} выбрана!*\n\n⏳ Открывается...", parse_mode=ParseMode.MARKDOWN)
    try:
        interp = groq_client.interpret_card_of_day(chosen)
        text = f"🌅 *Ваша карта дня: {chosen['name']}*\nСтихия: {chosen['element']}\n\n{'─'*30}\n\n{interp}\n\n{'─'*30}\n✨ _Пусть день будет наполнен светом!_"
    except Exception as e:
        logger.error(f"Groq COD: {e}")
        text = f"🌅 *Ваша карта дня: {chosen['name']}*\n\nКлючевые слова: _{chosen['keywords']}_\n\n⚠️ Интерпретация недоступна. Попробуйте позже."
    await q.edit_message_text(text, reply_markup=back_kb(), parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────── Информация ──────────────────────────────

async def handle_info(q):
    await q.edit_message_text(
        "ℹ️ *Информация о боте*\n\n"
        "Персональный таро-ассистент на основе ИИ.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔮 *Возможности:*\n"
        "• 🔮 Задать вопрос — расклад из трёх карт\n"
        "• 🎴 Расклады — 10 тематических раскладов\n"
        "• 🌅 Карта дня — бесплатно каждый день!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💳 *Тарифы (ЮKassa, картой):*\n"
        "🌙 99₽ — 3 расклада\n"
        "⭐ 249₽ — 10 раскладов\n"
        "🔥 499₽ — 25 раскладов\n"
        "👑 999₽ — 100 раскладов\n\n"
        "⭐ *Тарифы (Telegram Stars):*\n"
        "1 звезда = 100 запросов\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📬 Уведомления о карте дня — ежедневно в 12:00 МСК.\n\n"
        "✨ _Таро — инструмент самопознания._",
        reply_markup=back_kb(), parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────── Текстовые сообщения ─────────────────────

async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state", STATE_IDLE)
    uid   = update.effective_user.id
    text  = update.message.text.strip()
    if state == STATE_ASK_QUESTION:
        await handle_user_question(update, context, uid, text)
    elif state == STATE_SPREAD_QUESTION:
        key = context.user_data.get("current_spread")
        if not key or key not in SPREADS:
            await update.message.reply_text("⚠️ Расклад не выбран.", reply_markup=back_kb())
            context.user_data["state"] = STATE_IDLE; return
        await handle_spread_question(update, context, uid, text, key)
    else:
        await update.message.reply_text("Выберите действие 👇", reply_markup=main_menu_keyboard())

async def handle_user_question(update, context, uid, question):
    context.user_data["state"] = STATE_IDLE
    if not db.has_active_subscription(uid):
        await update.message.reply_text("🔒 *Нет подписки.*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Купить", callback_data="subscribe")],[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]), parse_mode=ParseMode.MARKDOWN); return
    if not db.use_request(uid):
        await update.message.reply_text("🔒 *Запросы закончились.*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Пополнить", callback_data="subscribe")],[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]), parse_mode=ParseMode.MARKDOWN); return
    think = await update.message.reply_text("🔮 *Карты тасуются...*", parse_mode=ParseMode.MARKDOWN)
    cards = draw_cards(3); ct = format_cards_text(cards); rl = db.get_requests_left(uid)
    try:
        interp = groq_client.interpret_three_cards(question, cards)
        res = f"🔮 *Расклад:*\n_«{question}»_\n\n{'─'*28}\n\n🃏 *Карты:*\n\n{ct}\n\n{'─'*28}\n\n✨ *Интерпретация:*\n\n{interp}\n\n{'─'*28}\n_Осталось: {rl}_"
    except Exception as e:
        logger.error(f"Groq: {e}"); res = f"🔮 _«{question}»_\n\n{ct}\n\n⚠️ Ошибка. Попробуйте снова.\n_Осталось: {rl}_"
    await think.delete()
    await update.message.reply_text(res, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔮 Ещё вопрос", callback_data="ask_question")],[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]), parse_mode=ParseMode.MARKDOWN)

async def handle_spread_question(update, context, uid, question, key):
    context.user_data["state"] = STATE_IDLE; context.user_data.pop("current_spread", None)
    s = SPREADS[key]
    if not db.has_active_subscription(uid):
        await update.message.reply_text("🔒 *Нет подписки.*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Купить", callback_data="subscribe")],[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]), parse_mode=ParseMode.MARKDOWN); return
    if not db.use_request(uid):
        await update.message.reply_text("🔒 *Запросы закончились.*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Пополнить", callback_data="subscribe")],[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]), parse_mode=ParseMode.MARKDOWN); return
    think = await update.message.reply_text(f"🎴 *{s['name']}*\n\nКарты тасуются...", parse_mode=ParseMode.MARKDOWN)
    cards = draw_cards(s["card_count"]); ct = format_cards_text(cards); rl = db.get_requests_left(uid)
    try:
        interp = groq_client.interpret_spread(spread_name=s["name"], question=question, cards=cards, positions=s["positions"])
        pos = "\n".join([f"*{i+1}. {s['positions'][i]}*\n   🃏 {cards[i]['name']}" for i in range(len(cards))])
        res = f"{s['emoji']} *{s['name']}*\n_«{question}»_\n\n{'─'*28}\n\n🃏 *Карты:*\n\n{pos}\n\n{'─'*28}\n\n✨ *Интерпретация:*\n\n{interp}\n\n{'─'*28}\n_Осталось: {rl}_"
    except Exception as e:
        logger.error(f"Groq spread: {e}"); res = f"{s['emoji']} *{s['name']}*\n_«{question}»_\n\n{ct}\n\n⚠️ Ошибка.\n_Осталось: {rl}_"
    await think.delete()
    await update.message.reply_text(res, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎴 Ещё расклад", callback_data="spreads")],[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]), parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────── Уведомления ─────────────────────────────

async def daily_notify(app: Application):
    logger.info("Рассылка карты дня...")
    ok = err = 0
    for tid in db.get_all_user_ids():
        try:
            await app.bot.send_message(
                chat_id=tid,
                text="🌅 *Карта дня обновлена!*\n\nВаша карта Таро готова ✨ Выберите одну из трёх:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌅 Открыть карту дня", callback_data="card_of_day")]]),
                parse_mode=ParseMode.MARKDOWN,
            )
            ok += 1
        except Exception as e: logger.warning(f"Notify {tid}: {e}"); err += 1
    logger.info(f"Рассылка: {ok} OK, {err} ошибок")

# ─────────────────────────── Запуск ──────────────────────────────────

async def start_webhook_server(app: Application):
    web_app = web.Application()
    web_app["bot_app"] = app
    web_app.router.add_post("/yookassa/webhook", yookassa_webhook)
    web_app.router.add_get("/health", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT).start()
    logger.info(f"Webhook-сервер запущен: порт {WEBHOOK_PORT}")

def main():
    if not TOKEN: raise ValueError("TELEGRAM_TOKEN не задан")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu",  start))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    scheduler.add_job(daily_notify, "cron", hour=12, minute=0, args=[app])
    scheduler.start()
    logger.info("Планировщик 12:00 МСК запущен")

    app.post_init = start_webhook_server

    logger.info("🔮 Таро-бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
