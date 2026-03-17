import os
import logging
import httpx

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"  # Лучшая бесплатная модель Groq


def _call_groq(system_prompt: str, user_message: str, max_tokens: int = 1500) -> str:
    """Базовый вызов Groq API"""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY не задан")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.85,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(GROQ_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        logger.error(f"Groq API HTTP error: {e.response.status_code} — {e.response.text}")
        raise
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        raise


# ============================================================
# Интерпретация трёх карт (вопрос пользователя)
# ============================================================
def interpret_three_cards(question: str, cards: list) -> str:
    """
    Интерпретация трёх карт под вопрос пользователя.
    cards — список словарей из tarot_cards.py
    """
    system_prompt = (
        "Ты — мудрый и опытный таролог с глубоким знанием символики карт Таро. "
        "Ты отвечаешь на русском языке, говоришь мягко, вдохновляюще и проницательно. "
        "Ты интерпретируешь карты в контексте конкретного вопроса пользователя. "
        "Используй эмодзи для красоты и атмосферы. "
        "Структура ответа:\n"
        "1. Краткое вступление\n"
        "2. Интерпретация каждой карты (название + позиция + смысл)\n"
        "3. Общий вывод и совет\n"
        "Пиши живо, атмосферно, но конкретно. Не более 800 слов."
    )

    cards_text = "\n".join([
        f"Карта {i+1}: {c['name']} (Стихия: {c['element']}, Ключевые слова: {c['keywords']})"
        for i, c in enumerate(cards)
    ])

    user_message = (
        f"Вопрос пользователя: «{question}»\n\n"
        f"Выпавшие карты:\n{cards_text}\n\n"
        "Проинтерпретируй эти три карты в контексте вопроса. "
        "Первая карта — прошлое/основа, вторая — настоящее/суть, третья — будущее/совет."
    )

    return _call_groq(system_prompt, user_message)


# ============================================================
# Интерпретация расклада
# ============================================================
def interpret_spread(
    spread_name: str,
    question: str,
    cards: list,
    positions: list
) -> str:
    """
    Интерпретация расклада с позициями.
    cards и positions — параллельные списки.
    """
    system_prompt = (
        "Ты — мудрый и опытный таролог с глубоким знанием символики карт Таро. "
        "Ты отвечаешь на русском языке, говоришь мягко, вдохновляюще и проницательно. "
        "Ты интерпретируешь карты строго по их позициям в раскладе, в контексте вопроса. "
        "Используй эмодзи для атмосферы. "
        "Структура ответа:\n"
        "1. Краткое вступление о раскладе и вопросе\n"
        "2. Каждая карта: её название, позиция и детальная интерпретация\n"
        "3. Общий вывод, послание и практический совет\n"
        "Пиши атмосферно, глубоко, но понятно. Не более 1000 слов."
    )

    positions_text = "\n".join([
        f"Позиция {i+1} «{positions[i]}»: {cards[i]['name']} "
        f"(Стихия: {cards[i]['element']}, Ключевые слова: {cards[i]['keywords']})"
        for i in range(min(len(cards), len(positions)))
    ])

    user_message = (
        f"Расклад: {spread_name}\n"
        f"Вопрос пользователя: «{question}»\n\n"
        f"Карты по позициям:\n{positions_text}\n\n"
        "Проинтерпретируй каждую карту в соответствии с её позицией в раскладе "
        "и дай полное, глубокое прочтение этого расклада."
    )

    return _call_groq(system_prompt, user_message, max_tokens=2000)


# ============================================================
# Карта дня
# ============================================================
def interpret_card_of_day(card: dict) -> str:
    """Интерпретация карты дня"""
    system_prompt = (
        "Ты — мудрый таролог. Ты даёшь вдохновляющее послание карты дня. "
        "Отвечай на русском языке, тепло и поддерживающе. "
        "Используй эмодзи. "
        "Структура:\n"
        "1. Приветствие и название карты\n"
        "2. Общий смысл и энергия карты\n"
        "3. Послание на сегодняшний день\n"
        "4. Практический совет на день\n"
        "5. Аффирмация дня (одна вдохновляющая фраза)\n"
        "Пиши кратко и воодушевляюще, не более 400 слов."
    )

    user_message = (
        f"Карта дня: {card['name']}\n"
        f"Стихия: {card['element']}\n"
        f"Ключевые слова: {card['keywords']}\n\n"
        "Дай послание этой карты на сегодняшний день — что она хочет сказать человеку, "
        "какую энергию несёт и каков её практический совет."
    )

    return _call_groq(system_prompt, user_message, max_tokens=800)
