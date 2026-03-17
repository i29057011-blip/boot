import os
import logging
import random
from datetime import datetime
import pytz
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
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

# Состояния пользователя (хранятся в context.user_data)
STATE_IDLE = "idle"
STATE_ASK_QUESTION = "ask_question"
STATE_SPREAD_QUESTION = "spread_question"

# Сайты для "редиректа" при оплате (заглушка)
FAKE_PAYMENT_SITES = [
    "https://www.sberbank.ru",
    "https://www.tinkoff.ru",
    "https://www.yoomoney.ru",
]

SUBSCRIPTION_PLANS = [
    {"name": "🌙 Стартовый", "requests": 3, "price": 99, "label": "plan_3"},
    {"name": "⭐ Популярный", "requests": 10, "price": 249, "label": "plan_10"},
    {"name": "🔥 Продвинутый", "requests": 30, "price": 599, "label": "plan_30"},
    {"name": "👑 VIP", "requests": 100, "price": 999, "label": "plan_100"},
]


# ============================================================
# Вспомогательные клавиатуры
# ============================================================

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔮 Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton("🎴 Расклады", callback_data="spreads")],
        [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
        [InlineKeyboardButton("🌅 Карта дня", callback_data="card_of_day")],
        [InlineKeyboardButton("ℹ️ Информация", callback_data="info")],
    ])


def back_to_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ])


def spreads_keyboard():
    buttons = []
    for key, spread in SPREADS.items():
        buttons.append([InlineKeyboardButton(spread["name"], callback_data=f"spread_{key}")])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def subscribe_keyboard():
    buttons = []
    for plan in SUBSCRIPTION_PLANS:
        buttons.append([
            InlineKeyboardButton(
                f"{plan['name']} — {plan['requests']} запросов за {plan['price']}₽",
                callback_data=f"pay_{plan['label']}"
            )
        ])
    buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def card_of_day_keyboard(pending_cards: list):
    """Три закрытые карты для выбора"""
    buttons = [
        InlineKeyboardButton("🂠 Карта 1", callback_data="pick_card_0"),
        InlineKeyboardButton("🂠 Карта 2", callback_data="pick_card_1"),
        InlineKeyboardButton("🂠 Карта 3", callback_data="pick_card_2"),
    ]
    return InlineKeyboardMarkup([buttons, [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]])


def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="main_menu")]
    ])


# ============================================================
# /start
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )
    context.user_data["state"] = STATE_IDLE

    welcome_text = (
        f"✨ *Добро пожаловать в Таро-бота, {user.first_name}!* ✨\n\n"
        "Я — ваш персональный проводник в мире Таро. "
        "Здесь вы найдёте ответы на важные вопросы, узнаете, что готовит судьба, "
        "и получите мудрые советы от древних символов.\n\n"
        "🔮 *Что я умею:*\n"
        "• Отвечать на ваши личные вопросы\n"
        "• Делать глубокие расклады по разным темам\n"
        "• Каждый день дарить вам карту дня\n"
        "• Направлять и вдохновлять\n\n"
        "Выберите действие в меню ниже 👇"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# Обработчик callback-кнопок
# ============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # ── Главное меню ──────────────────────────────────────────
    if data == "main_menu":
        context.user_data["state"] = STATE_IDLE
        context.user_data.pop("current_spread", None)
        await query.edit_message_text(
            "🏠 *Главное меню*\n\nВыберите действие:",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Задать вопрос ─────────────────────────────────────────
    elif data == "ask_question":
        if not db.has_active_subscription(user_id):
            await query.edit_message_text(
                "🔒 *Нет активной подписки*\n\n"
                "У вас нет активной подписки. Оформите подписку, чтобы задавать вопросы.\n\n"
                "Функция *«Задать вопрос»* позволяет:\n"
                "• Ввести любой личный вопрос\n"
                "• Получить расклад из трёх карт\n"
                "• Узнать глубинный смысл в контексте вашего вопроса",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
                ]),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        requests_left = db.get_requests_left(user_id)
        context.user_data["state"] = STATE_ASK_QUESTION
        await query.edit_message_text(
            f"🔮 *Задайте ваш вопрос*\n\n"
            f"У вас осталось запросов: *{requests_left}*\n\n"
            "Сформулируйте вопрос чётко и с намерением. "
            "Чем конкретнее вопрос — тем точнее ответ карт.\n\n"
            "💬 *Напишите ваш вопрос:*",
            reply_markup=cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Расклады ─────────────────────────────────────────────
    elif data == "spreads":
        context.user_data["state"] = STATE_IDLE
        spreads_text = "🎴 *Расклады Таро*\n\nВыберите тему расклада:\n"
        await query.edit_message_text(
            spreads_text,
            reply_markup=spreads_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("spread_"):
        spread_key = data.replace("spread_", "")
        if spread_key not in SPREADS:
            await query.edit_message_text("Расклад не найден.", reply_markup=back_to_menu_keyboard())
            return

        spread = SPREADS[spread_key]
        context.user_data["state"] = STATE_IDLE
        context.user_data["current_spread"] = spread_key

        text = (
            f"{spread['emoji']} *{spread['name']}*\n\n"
            f"_{spread['full_desc']}_\n\n"
            f"{spread['how_to_ask']}"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎴 Начать расклад", callback_data=f"start_spread_{spread_key}")],
                [InlineKeyboardButton("◀️ Назад к раскладам", callback_data="spreads")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
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
                "🔒 *Нет активной подписки*\n\n"
                "Для проведения расклада необходима активная подписка.\n"
                "Вы можете бесплатно просматривать описания всех раскладов, "
                "но для получения расклада нужна подписка.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
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
            f"🎴 *{spread['name']}*\n\n"
            f"У вас осталось запросов: *{requests_left}*\n\n"
            "Сформулируйте свой вопрос для этого расклада. "
            "Помните об инструкции выше — чем точнее вопрос, тем глубже ответ.\n\n"
            "💬 *Введите ваш вопрос:*",
            reply_markup=cancel_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Подписка ─────────────────────────────────────────────
    elif data == "subscribe":
        requests_left = db.get_requests_left(user_id)
        text = (
            "💳 *Оформление подписки*\n\n"
            f"Ваш текущий баланс: *{requests_left} запросов*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📦 *Доступные планы:*\n\n"
            "🌙 *Стартовый* — 3 запроса за *99 ₽*\n"
            "   Идеально для знакомства\n\n"
            "⭐ *Популярный* — 10 запросов за *249 ₽*\n"
            "   Лучший выбор для регулярных консультаций\n\n"
            "🔥 *Продвинутый* — 30 запросов за *599 ₽*\n"
            "   Для тех, кто серьёзно работает с Таро\n\n"
            "👑 *VIP* — 100 запросов за *999 ₽*\n"
            "   Безграничные возможности\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋 *Инструкция по оплате:*\n"
            "1. Выберите подходящий план\n"
            "2. Нажмите на кнопку оплаты\n"
            "3. Вы будете перенаправлены на страницу оплаты\n"
            "4. После успешной оплаты запросы зачислятся автоматически\n\n"
            "⚡ Запросы не сгорают и накапливаются!"
        )
        await query.edit_message_text(
            text,
            reply_markup=subscribe_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("pay_"):
        plan_label = data.replace("pay_", "")
        plan = next((p for p in SUBSCRIPTION_PLANS if p["label"] == plan_label), None)
        if not plan:
            await query.answer("План не найден", show_alert=True)
            return

        fake_url = random.choice(FAKE_PAYMENT_SITES)
        await query.edit_message_text(
            f"💳 *Оплата: {plan['name']}*\n\n"
            f"Сумма к оплате: *{plan['price']} ₽*\n"
            f"Вы получите: *{plan['requests']} запросов*\n\n"
            "⏳ Система оплаты находится в разработке.\n"
            "Скоро здесь появится удобная оплата картой!\n\n"
            "Пока вы можете ознакомиться с нашей страницей:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Перейти к оплате", url=fake_url)],
                [InlineKeyboardButton("◀️ Назад к планам", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Карта дня ─────────────────────────────────────────────
    elif data == "card_of_day":
        await handle_card_of_day(query, user_id)

    elif data.startswith("pick_card_"):
        card_index = int(data.replace("pick_card_", ""))
        await handle_pick_card(query, user_id, card_index, context)

    # ── Информация ────────────────────────────────────────────
    elif data == "info":
        await handle_info(query)


# ============================================================
# Карта дня
# ============================================================

async def handle_card_of_day(query, user_id: int):
    if db.already_picked_card_today(user_id):
        info = db.get_card_of_day_info(user_id)
        card_name = info.get("card_of_day_card", "неизвестна")
        await query.edit_message_text(
            f"🌅 *Карта дня*\n\n"
            f"Вы уже выбрали карту сегодня: *{card_name}* 🃏\n\n"
            "Карта дня обновляется ежедневно в *12:00 по Москве*.\n"
            "Приходите завтра за новым посланием! ✨",
            reply_markup=back_to_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if db.already_started_card_today(user_id):
        # Уже начал выбор — показать снова три карты
        pending_cards = db.get_pending_cards(user_id)
        await query.edit_message_text(
            "🌅 *Карта дня*\n\n"
            "Вы уже начали выбор сегодня. Выберите одну из трёх закрытых карт — "
            "она расскажет, что ждёт вас в этот день 🔮\n\n"
            "👇 *Выберите карту:*",
            reply_markup=card_of_day_keyboard(pending_cards),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Новый выбор — создать 3 случайные карты
    pending_cards = draw_cards(3)
    pending_data = [{"name": c["name"], "element": c["element"], "keywords": c["keywords"]}
                    for c in pending_cards]
    db.set_card_of_day_pending(user_id, pending_data)

    await query.edit_message_text(
        "🌅 *Карта дня*\n\n"
        "Перед вами три закрытые карты. "
        "Сосредоточьтесь, прислушайтесь к своей интуиции "
        "и выберите ту, что привлекает вас сильнее всего 🔮\n\n"
        "Эта карта расскажет вам о сегодняшнем дне:\n\n"
        "👇 *Выберите карту:*",
        reply_markup=card_of_day_keyboard(pending_cards),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_pick_card(query, user_id: int, card_index: int, context):
    pending_cards = db.get_pending_cards(user_id)
    if not pending_cards or card_index >= len(pending_cards):
        await query.edit_message_text(
            "⚠️ Ошибка. Пожалуйста, начните выбор карты дня заново.",
            reply_markup=back_to_menu_keyboard()
        )
        return

    chosen_card = pending_cards[card_index]
    db.choose_card_of_day(user_id, chosen_card)

    await query.edit_message_text(
        f"🎴 *Вы выбрали карту {card_index + 1}!*\n\n"
        "⏳ Карта открывается... Обращаюсь к мудрости Таро...",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        interpretation = groq_client.interpret_card_of_day(chosen_card)
        card_text = (
            f"🌅 *Ваша карта дня: {chosen_card['name']}*\n"
            f"Стихия: {chosen_card['element']}\n\n"
            f"{'─' * 30}\n\n"
            f"{interpretation}\n\n"
            f"{'─' * 30}\n"
            f"✨ _Пусть этот день будет наполнен светом и мудростью!_"
        )
    except Exception as e:
        logger.error(f"Groq error in card of day: {e}")
        card_text = (
            f"🌅 *Ваша карта дня: {chosen_card['name']}*\n\n"
            f"Ключевые слова: _{chosen_card['keywords']}_\n\n"
            "⚠️ Не удалось получить расширенную интерпретацию. Попробуйте позже."
        )

    await query.edit_message_text(
        card_text,
        reply_markup=back_to_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# Информация
# ============================================================

async def handle_info(query):
    info_text = (
        "ℹ️ *Информация о боте*\n\n"
        "Я — ваш персональный таро-ассистент, работающий на основе "
        "искусственного интеллекта и мудрости карт Таро.\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔮 *Что умеет бот:*\n\n"

        "• *🔮 Задать вопрос* — введите любой личный вопрос, "
        "и бот вытащит три карты с детальной интерпретацией именно для вас\n\n"

        "• *🎴 Расклады* — 10 специализированных раскладов по разным темам: "
        "от отношений до духовного пути\n\n"

        "• *🌅 Карта дня* — бесплатно, каждый день! "
        "Выберите из трёх закрытых карт ту, что говорит с вашей интуицией, "
        "и получите послание на день\n\n"

        "• *💳 Подписка* — пополните баланс запросов для работы с раскладами\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎴 *Доступные расклады:*\n\n"
        "💕 Расклад на отношения — динамика и чувства в паре\n"
        "💰 Расклад на финансы — деньги, блоки и возможности\n"
        "🚀 Расклад на карьеру — профессиональный рост\n"
        "⚖️ Расклад Да/Нет — чёткий ответ на закрытый вопрос\n"
        "🌿 Расклад на здоровье — энергетическое состояние\n"
        "🔮 Расклад на будущее — прошлое, настоящее, будущее\n"
        "🤔 Расклад на принятие решения — путь выбора\n"
        "🌟 Расклад на самопознание — ваши дары и тени\n"
        "🍀 Расклад на удачу — где ждёт везение\n"
        "✨ Расклад на духовный путь — предназначение\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *Технология:*\n"
        "Интерпретации создаются с помощью передовых нейросетей "
        "на основе глубокого знания символики Таро.\n\n"

        "📬 *Уведомления:*\n"
        "Каждый день в 12:00 по Москве вы получите сообщение "
        "о том, что карта дня обновлена.\n\n"
        "✨ _Таро — это инструмент самопознания. Карты не предсказывают судьбу, "
        "а отражают энергии и помогают принимать осознанные решения._"
    )

    await query.edit_message_text(
        info_text,
        reply_markup=back_to_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# Обработчик текстовых сообщений (вопросы пользователя)
# ============================================================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state", STATE_IDLE)
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if state == STATE_ASK_QUESTION:
        await handle_user_question(update, context, user_id, text)

    elif state == STATE_SPREAD_QUESTION:
        spread_key = context.user_data.get("current_spread")
        if not spread_key or spread_key not in SPREADS:
            await update.message.reply_text(
                "⚠️ Расклад не выбран. Вернитесь в меню.",
                reply_markup=back_to_menu_keyboard()
            )
            context.user_data["state"] = STATE_IDLE
            return
        await handle_spread_question(update, context, user_id, text, spread_key)

    else:
        await update.message.reply_text(
            "Выберите действие в меню 👇",
            reply_markup=main_menu_keyboard(),
        )


async def handle_user_question(update, context, user_id: int, question: str):
    """Обработать вопрос пользователя (расклад из 3 карт)"""
    context.user_data["state"] = STATE_IDLE

    if not db.has_active_subscription(user_id):
        await update.message.reply_text(
            "🔒 *У вас нет активной подписки.*\n\nОформите подписку для доступа к раскладам.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not db.use_request(user_id):
        await update.message.reply_text(
            "🔒 *Запросы закончились.*\n\nПополните баланс для продолжения.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Пополнить баланс", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    thinking_msg = await update.message.reply_text(
        "🔮 *Карты тасуются...*\n\nСосредоточьтесь на своём вопросе...",
        parse_mode=ParseMode.MARKDOWN,
    )

    cards = draw_cards(3)
    cards_text = format_cards_text(cards)
    requests_left = db.get_requests_left(user_id)

    try:
        interpretation = groq_client.interpret_three_cards(question, cards)
        result_text = (
            f"🔮 *Расклад на ваш вопрос:*\n"
            f"_«{question}»_\n\n"
            f"{'─' * 30}\n\n"
            f"🃏 *Выпавшие карты:*\n\n{cards_text}\n\n"
            f"{'─' * 30}\n\n"
            f"✨ *Интерпретация:*\n\n{interpretation}\n\n"
            f"{'─' * 30}\n"
            f"_Осталось запросов: {requests_left}_"
        )
    except Exception as e:
        logger.error(f"Groq error: {e}")
        result_text = (
            f"🔮 *Расклад на ваш вопрос:*\n"
            f"_«{question}»_\n\n"
            f"🃏 *Выпавшие карты:*\n\n{cards_text}\n\n"
            "⚠️ Не удалось получить интерпретацию. Запрос был использован. "
            "Пожалуйста, попробуйте снова.\n\n"
            f"_Осталось запросов: {requests_left}_"
        )

    await thinking_msg.delete()
    await update.message.reply_text(
        result_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔮 Задать ещё вопрос", callback_data="ask_question")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_spread_question(update, context, user_id: int, question: str, spread_key: str):
    """Обработать вопрос для конкретного расклада"""
    context.user_data["state"] = STATE_IDLE
    context.user_data.pop("current_spread", None)
    spread = SPREADS[spread_key]

    if not db.has_active_subscription(user_id):
        await update.message.reply_text(
            "🔒 *У вас нет активной подписки.*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not db.use_request(user_id):
        await update.message.reply_text(
            "🔒 *Запросы закончились.* Пополните баланс.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Пополнить баланс", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    thinking_msg = await update.message.reply_text(
        f"🎴 *{spread['name']}*\n\n"
        "Карты тасуются... Пространство раскрывается...",
        parse_mode=ParseMode.MARKDOWN,
    )

    cards = draw_cards(spread["card_count"])
    cards_text = format_cards_text(cards)
    requests_left = db.get_requests_left(user_id)

    try:
        interpretation = groq_client.interpret_spread(
            spread_name=spread["name"],
            question=question,
            cards=cards,
            positions=spread["positions"],
        )
        # Построить красивый заголовок с картами по позициям
        positions_display = "\n".join([
            f"*{i+1}. {spread['positions'][i]}*\n   🃏 {cards[i]['name']}"
            for i in range(len(cards))
        ])

        result_text = (
            f"{spread['emoji']} *{spread['name']}*\n"
            f"_«{question}»_\n\n"
            f"{'─' * 30}\n\n"
            f"🃏 *Карты расклада:*\n\n{positions_display}\n\n"
            f"{'─' * 30}\n\n"
            f"✨ *Полная интерпретация:*\n\n{interpretation}\n\n"
            f"{'─' * 30}\n"
            f"_Осталось запросов: {requests_left}_"
        )
    except Exception as e:
        logger.error(f"Groq spread error: {e}")
        result_text = (
            f"{spread['emoji']} *{spread['name']}*\n"
            f"_«{question}»_\n\n"
            f"🃏 *Выпавшие карты:*\n\n{cards_text}\n\n"
            "⚠️ Не удалось получить интерпретацию. Попробуйте снова.\n\n"
            f"_Осталось запросов: {requests_left}_"
        )

    await thinking_msg.delete()
    await update.message.reply_text(
        result_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎴 Ещё расклад", callback_data="spreads")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]),
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# Ежедневные уведомления (12:00 МСК)
# ============================================================

async def send_daily_notifications(app):
    """Рассылка уведомлений всем пользователям"""
    logger.info("Отправка ежедневных уведомлений о карте дня...")
    user_ids = db.get_all_user_ids()
    success = 0
    errors = 0

    for telegram_id in user_ids:
        try:
            await app.bot.send_message(
                chat_id=telegram_id,
                text=(
                    "🌅 *Карта дня обновлена!*\n\n"
                    "Ваша ежедневная карта Таро готова к открытию ✨\n\n"
                    "Сосредоточьтесь, прислушайтесь к интуиции "
                    "и выберите карту, которая говорит с вашей душой.\n\n"
                    "Нажмите 👇 чтобы узнать, что готовит вам этот день:"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌅 Открыть карту дня", callback_data="card_of_day")]
                ]),
                parse_mode=ParseMode.MARKDOWN,
            )
            success += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление {telegram_id}: {e}")
            errors += 1

    logger.info(f"Уведомления: {success} успешно, {errors} ошибок")


# ============================================================
# Запуск бота
# ============================================================

def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_TOKEN не задан в .env")

    app = Application.builder().token(TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))

    # Callback-кнопки
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Планировщик для ежедневных уведомлений в 12:00 МСК
    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    scheduler.add_job(
        send_daily_notifications,
        trigger="cron",
        hour=12,
        minute=0,
        args=[app],
    )
    scheduler.start()
    logger.info("Планировщик уведомлений запущен (12:00 МСК)")

    logger.info("🔮 Таро-бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
