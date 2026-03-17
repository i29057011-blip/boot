import os
import logging
import random
from datetime import datetime
import pytz
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from dotenv import load_dotenv
import database as db
import groq_client
from tarot_cards import TAROT_CARDS, SPREADS, draw_cards, format_cards_text
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

STATE_IDLE = "idle"
STATE_ASK_QUESTION = "ask_question"
STATE_SPREAD_QUESTION = "spread_question"

STARS_PLANS = [
    {"label": "stars_1",  "name": "🌙 Пробный",      "stars": 1,  "requests": 100,  "desc": "Идеально для знакомства"},
    {"label": "stars_5",  "name": "⭐ Популярный",   "stars": 5,  "requests": 500,  "desc": "Лучший выбор"},
    {"label": "stars_15", "name": "🔥 Продвинутый",  "stars": 15, "requests": 1500, "desc": "Для серьёзной работы"},
    {"label": "stars_50", "name": "👑 VIP",           "stars": 50, "requests": 5000, "desc": "Безграничные возможности"},
]
STARS_PLANS_BY_LABEL = {p["label"]: p for p in STARS_PLANS}


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔮 Задать вопрос",     callback_data="ask_question")],
        [InlineKeyboardButton("🎴 Расклады",          callback_data="spreads")],
        [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
        [InlineKeyboardButton("🌅 Карта дня",         callback_data="card_of_day")],
        [InlineKeyboardButton("ℹ️ Информация",         callback_data="info")],
    ])

def back_to_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]])

def spreads_keyboard():
    buttons = [[InlineKeyboardButton(s["name"], callback_data=f"spread_{k}")] for k, s in SPREADS.items()]
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def subscribe_keyboard():
    buttons = [
        [InlineKeyboardButton(
            f"⭐ {p['stars']} звезд → {p['requests']} запросов  ({p['name']})",
            callback_data=f"buy_stars_{p['label']}"
        )]
        for p in STARS_PLANS
    ]
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def card_of_day_keyboard(pending_cards):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🂠 Карта 1", callback_data="pick_card_0"),
         InlineKeyboardButton("🂠 Карта 2", callback_data="pick_card_1"),
         InlineKeyboardButton("🂠 Карта 3", callback_data="pick_card_2")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="main_menu")]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(telegram_id=user.id, username=user.username, first_name=user.first_name)
    context.user_data["state"] = STATE_IDLE
    await update.message.reply_text(
        f"✨ *Добро пожаловать в Таро-бота, {user.first_name}!* ✨\n\n"
        "Я — ваш персональный проводник в мире Таро. "
        "Здесь вы найдёте ответы на важные вопросы, узнаете, что готовит судьба, "
        "и получите мудрые советы от древних символов.\n\n"
        "🔮 *Что я умею:*\n"
        "• Отвечать на ваши личные вопросы\n"
        "• Делать глубокие расклады по разным темам\n"
        "• Каждый день дарить вам карту дня\n"
        "• Направлять и вдохновлять\n\n"
        "💫 *Оплата* — только через Telegram Stars ⭐\n\n"
        "Выберите действие в меню ниже 👇",
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "main_menu":
        context.user_data["state"] = STATE_IDLE
        context.user_data.pop("current_spread", None)
        await query.edit_message_text(
            "🏠 *Главное меню*\n\nВыберите действие:",
            reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "ask_question":
        if not db.has_active_subscription(user_id):
            await query.edit_message_text(
                "🔒 *Нет активной подписки*\n\n"
                "Оформите подписку за Telegram Stars, чтобы задавать вопросы.\n\n"
                "Функция *«Задать вопрос»* позволяет:\n"
                "• Ввести любой личный вопрос\n"
                "• Получить расклад из трёх карт\n"
                "• Узнать глубинный смысл в контексте вопроса",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⭐ Купить запросы", callback_data="subscribe")],
                    [InlineKeyboardButton("🏠 Главное меню",   callback_data="main_menu")],
                ]),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        requests_left = db.get_requests_left(user_id)
        context.user_data["state"] = STATE_ASK_QUESTION
        await query.edit_message_text(
            f"🔮 *Задайте ваш вопрос*\n\nОсталось запросов: *{requests_left}*\n\n"
            "Сформулируйте вопрос чётко и с намерением.\n\n💬 *Напишите ваш вопрос:*",
            reply_markup=cancel_keyboard(), parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "spreads":
        context.user_data["state"] = STATE_IDLE
        await query.edit_message_text(
            "🎴 *Расклады Таро*\n\nВыберите тему расклада:",
            reply_markup=spreads_keyboard(), parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("spread_"):
        spread_key = data.replace("spread_", "")
        if spread_key not in SPREADS:
            await query.edit_message_text("Расклад не найден.", reply_markup=back_to_menu_keyboard())
            return
        spread = SPREADS[spread_key]
        context.user_data["current_spread"] = spread_key
        await query.edit_message_text(
            f"{spread['emoji']} *{spread['name']}*\n\n_{spread['full_desc']}_\n\n{spread['how_to_ask']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎴 Начать расклад", callback_data=f"start_spread_{spread_key}")],
                [InlineKeyboardButton("◀️ К раскладам",    callback_data="spreads")],
                [InlineKeyboardButton("🏠 Главное меню",   callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("start_spread_"):
        spread_key = data.replace("start_spread_", "")
        if spread_key not in SPREADS:
            await query.edit_message_text("Расклад не найден.", reply_markup=back_to_menu_keyboard())
            return
        if not db.has_active_subscription(user_id):
            await query.edit_message_text(
                "🔒 *Нет активной подписки*\n\nТемы раскладов доступны бесплатно, "
                "а для проведения расклада нужна подписка.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⭐ Купить запросы", callback_data="subscribe")],
                    [InlineKeyboardButton("◀️ Назад", callback_data=f"spread_{spread_key}")],
                ]),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        spread = SPREADS[spread_key]
        requests_left = db.get_requests_left(user_id)
        context.user_data["state"] = STATE_SPREAD_QUESTION
        context.user_data["current_spread"] = spread_key
        await query.edit_message_text(
            f"🎴 *{spread['name']}*\n\nОсталось запросов: *{requests_left}*\n\n"
            "Введите вопрос для этого расклада:\n\n💬 *Ваш вопрос:*",
            reply_markup=cancel_keyboard(), parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "subscribe":
        requests_left = db.get_requests_left(user_id)
        plans_text = "\n\n".join([
            f"{'⭐' * min(p['stars'], 5)}{'…' if p['stars'] > 5 else ''} "
            f"*{p['name']}* — {p['stars']} ⭐ → {p['requests']} запросов\n   _{p['desc']}_"
            for p in STARS_PLANS
        ])
        await query.edit_message_text(
            f"⭐ *Оплата через Telegram Stars*\n\n"
            f"Ваш баланс: *{requests_left} запросов*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💫 *Курс:* 1 звезда = 100 запросов\n\n"
            f"{plans_text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Запросы *накапливаются* и не сгорают.\n"
            "Нажмите на план — откроется окно оплаты Telegram 👇",
            reply_markup=subscribe_keyboard(), parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("buy_stars_"):
        plan_label = data.replace("buy_stars_", "")
        plan = STARS_PLANS_BY_LABEL.get(plan_label)
        if not plan:
            await query.answer("План не найден", show_alert=True)
            return
        await query.message.reply_invoice(
            title=f"{plan['name']} — {plan['requests']} запросов",
            description=(
                f"Таро-бот: {plan['requests']} запросов для раскладов.\n"
                f"Курс: 1 ⭐ = 100 запросов. {plan['desc']}."
            ),
            payload=plan_label,
            provider_token="",   # пустой = Stars
            currency="XTR",      # Telegram Stars
            prices=[LabeledPrice(label=f"{plan['requests']} запросов", amount=plan["stars"])],
        )

    elif data == "card_of_day":
        await handle_card_of_day(query, user_id)

    elif data.startswith("pick_card_"):
        card_index = int(data.replace("pick_card_", ""))
        await handle_pick_card(query, user_id, card_index, context)

    elif data == "info":
        await handle_info(query)


# ── Telegram Stars: Pre-checkout (ОБЯЗАТЕЛЬНО ответить за 10 сек) ──

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    plan = STARS_PLANS_BY_LABEL.get(query.invoice_payload)
    if plan:
        await query.answer(ok=True)
        logger.info(f"Pre-checkout OK: user={query.from_user.id} plan={plan['label']}")
    else:
        await query.answer(ok=False, error_message="Неизвестный план подписки.")


# ── Telegram Stars: Успешная оплата — зачисляем запросы ────────────

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    user_id = update.effective_user.id
    plan_label = payment.invoice_payload
    stars_paid = payment.total_amount  # для XTR == количество звёзд

    plan = STARS_PLANS_BY_LABEL.get(plan_label)
    if not plan:
        logger.error(f"Unknown plan_label in successful_payment: {plan_label}")
        await update.message.reply_text(
            "⚠️ Оплата прошла, но план не распознан. Обратитесь в поддержку.",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    db.add_subscription(telegram_id=user_id, requests_count=plan["requests"], plan_name=plan["name"])
    requests_left = db.get_requests_left(user_id)
    logger.info(f"Payment OK: user={user_id} stars={stars_paid} +{plan['requests']} requests")

    await update.message.reply_text(
        f"✅ *Оплата прошла успешно!*\n\n"
        f"⭐ Вы заплатили: *{stars_paid} звезд*\n"
        f"🎁 Начислено: *{plan['requests']} запросов*\n"
        f"💼 Ваш баланс: *{requests_left} запросов*\n\n"
        "Теперь вы можете делать расклады и задавать вопросы 🔮\n"
        "Пусть карты ведут вас к истине! ✨",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔮 Задать вопрос", callback_data="ask_question")],
            [InlineKeyboardButton("🎴 Расклады",      callback_data="spreads")],
            [InlineKeyboardButton("🏠 Главное меню",  callback_data="main_menu")],
        ]),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Карта дня ───────────────────────────────────────────────────────

async def handle_card_of_day(query, user_id: int):
    if db.already_picked_card_today(user_id):
        info = db.get_card_of_day_info(user_id)
        card_name = info.get("card_of_day_card", "неизвестна")
        await query.edit_message_text(
            f"🌅 *Карта дня*\n\nВы уже выбрали карту сегодня: *{card_name}* 🃏\n\n"
            "Карта дня обновляется ежедневно в *12:00 по Москве*.\n"
            "Приходите завтра за новым посланием! ✨",
            reply_markup=back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN,
        )
        return

    if db.already_started_card_today(user_id):
        pending_cards = db.get_pending_cards(user_id)
        await query.edit_message_text(
            "🌅 *Карта дня*\n\nВы уже начали выбор. Выберите одну из трёх закрытых карт 🔮\n\n👇 *Выберите карту:*",
            reply_markup=card_of_day_keyboard(pending_cards), parse_mode=ParseMode.MARKDOWN,
        )
        return

    pending_cards = draw_cards(3)
    pending_data = [{"name": c["name"], "element": c["element"], "keywords": c["keywords"]} for c in pending_cards]
    db.set_card_of_day_pending(user_id, pending_data)
    await query.edit_message_text(
        "🌅 *Карта дня*\n\n"
        "Перед вами три закрытые карты. "
        "Сосредоточьтесь, прислушайтесь к своей интуиции "
        "и выберите ту, что привлекает вас сильнее всего 🔮\n\n"
        "👇 *Выберите карту:*",
        reply_markup=card_of_day_keyboard(pending_cards), parse_mode=ParseMode.MARKDOWN,
    )


async def handle_pick_card(query, user_id: int, card_index: int, context):
    pending_cards = db.get_pending_cards(user_id)
    if not pending_cards or card_index >= len(pending_cards):
        await query.edit_message_text("⚠️ Ошибка. Начните выбор карты дня заново.", reply_markup=back_to_menu_keyboard())
        return

    chosen_card = pending_cards[card_index]
    db.choose_card_of_day(user_id, chosen_card)
    await query.edit_message_text(f"🎴 *Вы выбрали карту {card_index + 1}!*\n\n⏳ Карта открывается...", parse_mode=ParseMode.MARKDOWN)

    try:
        interpretation = groq_client.interpret_card_of_day(chosen_card)
        card_text = (
            f"🌅 *Ваша карта дня: {chosen_card['name']}*\n"
            f"Стихия: {chosen_card['element']}\n\n{'─' * 30}\n\n"
            f"{interpretation}\n\n{'─' * 30}\n"
            f"✨ _Пусть этот день будет наполнен светом и мудростью!_"
        )
    except Exception as e:
        logger.error(f"Groq error in card of day: {e}")
        card_text = (
            f"🌅 *Ваша карта дня: {chosen_card['name']}*\n\n"
            f"Ключевые слова: _{chosen_card['keywords']}_\n\n"
            "⚠️ Не удалось получить интерпретацию. Попробуйте позже."
        )
    await query.edit_message_text(card_text, reply_markup=back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)


async def handle_info(query):
    await query.edit_message_text(
        "ℹ️ *Информация о боте*\n\n"
        "Я — ваш персональный таро-ассистент на основе ИИ.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔮 *Возможности:*\n\n"
        "• *🔮 Задать вопрос* — три карты с интерпретацией ИИ\n"
        "• *🎴 Расклады* — 10 специализированных раскладов\n"
        "• *🌅 Карта дня* — бесплатно, каждый день!\n"
        "• *💳 Подписка* — оплата Telegram Stars ⭐\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎴 *Расклады:*\n"
        "💕 Отношения  💰 Финансы  🚀 Карьера\n"
        "⚖️ Да/Нет  🌿 Здоровье  🔮 Будущее\n"
        "🤔 Решение  🌟 Самопознание  🍀 Удача  ✨ Духовный путь\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⭐ *Оплата Stars:* 1 звезда = 100 запросов\n"
        "Запросы накапливаются и не сгорают.\n\n"
        "📬 Уведомления о карте дня — ежедневно в 12:00 МСК.\n\n"
        "✨ _Таро — инструмент самопознания, а не предсказания судьбы._",
        reply_markup=back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN,
    )


# ── Текстовые сообщения ─────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state", STATE_IDLE)
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if state == STATE_ASK_QUESTION:
        await handle_user_question(update, context, user_id, text)
    elif state == STATE_SPREAD_QUESTION:
        spread_key = context.user_data.get("current_spread")
        if not spread_key or spread_key not in SPREADS:
            await update.message.reply_text("⚠️ Расклад не выбран.", reply_markup=back_to_menu_keyboard())
            context.user_data["state"] = STATE_IDLE
            return
        await handle_spread_question(update, context, user_id, text, spread_key)
    else:
        await update.message.reply_text("Выберите действие в меню 👇", reply_markup=main_menu_keyboard())


async def handle_user_question(update, context, user_id, question):
    context.user_data["state"] = STATE_IDLE
    if not db.has_active_subscription(user_id):
        await update.message.reply_text(
            "🔒 *У вас нет активной подписки.*\n\nКупите запросы за Telegram Stars.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Купить запросы", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню",   callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if not db.use_request(user_id):
        await update.message.reply_text(
            "🔒 *Запросы закончились.* Пополните баланс.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Пополнить баланс", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню",     callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    thinking_msg = await update.message.reply_text(
        "🔮 *Карты тасуются...*\n\nСосредоточьтесь на своём вопросе...", parse_mode=ParseMode.MARKDOWN,
    )
    cards = draw_cards(3)
    cards_text = format_cards_text(cards)
    requests_left = db.get_requests_left(user_id)
    try:
        interpretation = groq_client.interpret_three_cards(question, cards)
        result_text = (
            f"🔮 *Расклад на ваш вопрос:*\n_«{question}»_\n\n{'─'*30}\n\n"
            f"🃏 *Выпавшие карты:*\n\n{cards_text}\n\n{'─'*30}\n\n"
            f"✨ *Интерпретация:*\n\n{interpretation}\n\n{'─'*30}\n"
            f"_Осталось запросов: {requests_left}_"
        )
    except Exception as e:
        logger.error(f"Groq error: {e}")
        result_text = (
            f"🔮 *Расклад на ваш вопрос:*\n_«{question}»_\n\n"
            f"🃏 *Карты:*\n\n{cards_text}\n\n"
            f"⚠️ Ошибка интерпретации. Попробуйте снова.\n\n_Осталось: {requests_left}_"
        )
    await thinking_msg.delete()
    await update.message.reply_text(
        result_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔮 Ещё вопрос",   callback_data="ask_question")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_spread_question(update, context, user_id, question, spread_key):
    context.user_data["state"] = STATE_IDLE
    context.user_data.pop("current_spread", None)
    spread = SPREADS[spread_key]
    if not db.has_active_subscription(user_id):
        await update.message.reply_text(
            "🔒 *У вас нет активной подписки.*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Купить запросы", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню",   callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if not db.use_request(user_id):
        await update.message.reply_text(
            "🔒 *Запросы закончились.*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Пополнить", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Меню",      callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    thinking_msg = await update.message.reply_text(
        f"🎴 *{spread['name']}*\n\nКарты тасуются...", parse_mode=ParseMode.MARKDOWN,
    )
    cards = draw_cards(spread["card_count"])
    cards_text = format_cards_text(cards)
    requests_left = db.get_requests_left(user_id)
    try:
        interpretation = groq_client.interpret_spread(
            spread_name=spread["name"], question=question, cards=cards, positions=spread["positions"]
        )
        positions_display = "\n".join([
            f"*{i+1}. {spread['positions'][i]}*\n   🃏 {cards[i]['name']}"
            for i in range(len(cards))
        ])
        result_text = (
            f"{spread['emoji']} *{spread['name']}*\n_«{question}»_\n\n{'─'*30}\n\n"
            f"🃏 *Карты расклада:*\n\n{positions_display}\n\n{'─'*30}\n\n"
            f"✨ *Полная интерпретация:*\n\n{interpretation}\n\n{'─'*30}\n"
            f"_Осталось запросов: {requests_left}_"
        )
    except Exception as e:
        logger.error(f"Groq spread error: {e}")
        result_text = (
            f"{spread['emoji']} *{spread['name']}*\n_«{question}»_\n\n"
            f"🃏 *Карты:*\n\n{cards_text}\n\n"
            f"⚠️ Ошибка интерпретации. Попробуйте снова.\n\n_Осталось: {requests_left}_"
        )
    await thinking_msg.delete()
    await update.message.reply_text(
        result_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎴 Ещё расклад",   callback_data="spreads")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Уведомления ─────────────────────────────────────────────────────

async def send_daily_notifications(app):
    logger.info("Отправка уведомлений о карте дня...")
    success = errors = 0
    for telegram_id in db.get_all_user_ids():
        try:
            await app.bot.send_message(
                chat_id=telegram_id,
                text="🌅 *Карта дня обновлена!*\n\nВаша ежедневная карта Таро готова ✨\nВыберите карту, которая говорит с вашей душой:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌅 Открыть карту дня", callback_data="card_of_day")]]),
                parse_mode=ParseMode.MARKDOWN,
            )
            success += 1
        except Exception as e:
            logger.warning(f"Уведомление {telegram_id}: {e}")
            errors += 1
    logger.info(f"Уведомления: {success} OK, {errors} ошибок")


# ── Запуск ──────────────────────────────────────────────────────────

def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_TOKEN не задан")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu",  start))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # ---- Telegram Stars Payments ----
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    # ---------------------------------

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    scheduler.add_job(send_daily_notifications, trigger="cron", hour=12, minute=0, args=[app])
    scheduler.start()
    logger.info("Планировщик 12:00 МСК запущен")

    logger.info("🔮 Таро-бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
