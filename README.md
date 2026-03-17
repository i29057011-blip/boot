# 🔮 Таро-бот для Telegram

Умный Telegram-бот для расклада карт Таро с интерпретацией через нейросеть Groq.

---

## ✨ Возможности

- **🔮 Задать вопрос** — расклад из 3 карт под личный вопрос (требует подписку)
- **🎴 Расклады** — 10 тематических раскладов: отношения, финансы, карьера и т.д.
- **🌅 Карта дня** — бесплатно, ежедневно для всех пользователей
- **💳 Подписка** — пополнение баланса запросов (4 тарифных плана)
- **📬 Уведомления** — ежедневно в 12:00 МСК о новой карте дня
- **🤖 AI-интерпретации** — через бесплатную нейросеть Groq (Llama 3.3 70B)

---

## 📁 Структура проекта

```
tarot_bot/
├── bot.py              # Основной файл бота
├── database.py         # Работа с Supabase
├── groq_client.py      # Запросы к Groq API
├── tarot_cards.py      # Данные карт и раскладов
├── requirements.txt    # Зависимости Python
├── Procfile            # Команда запуска для Railway
├── .env.example        # Шаблон переменных окружения
├── supabase_schema.sql # SQL-схема для базы данных
└── README.md
```

---

## 🗄️ Настройка Supabase (база данных)

### Шаг 1: Создать проект
1. Перейдите на [supabase.com](https://supabase.com) и зарегистрируйтесь
2. Нажмите **"New project"**
3. Заполните:
   - **Name**: `tarot-bot` (или любое другое)
   - **Database Password**: придумайте надёжный пароль (сохраните!)
   - **Region**: выберите ближайший (например, `eu-central-1` для Европы)
4. Нажмите **"Create new project"** — подождите ~2 минуты

### Шаг 2: Создать таблицы
1. В левом меню выберите **"SQL Editor"**
2. Нажмите **"New query"**
3. Скопируйте и вставьте весь код из файла `supabase_schema.sql`
4. Нажмите **"Run"** (или Ctrl+Enter)
5. Убедитесь, что появилось сообщение `Success. No rows returned`

### Шаг 3: Получить ключи API
1. В левом меню выберите **"Project Settings"** (иконка шестерёнки)
2. Выберите раздел **"API"**
3. Скопируйте:
   - **Project URL** → это ваш `SUPABASE_URL`
   - **anon / public** ключ → это ваш `SUPABASE_KEY`

> ⚠️ **Важно**: Используйте `anon` ключ, НЕ `service_role`. Бот работает со стороны сервера и для наших политик RLS этого достаточно.

### Шаг 4: Проверить таблицы
1. В левом меню выберите **"Table Editor"**
2. Вы должны увидеть таблицы: `users` и `spread_history`

---

## 🤖 Получение токена Telegram-бота

1. Напишите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте команду `/newbot`
3. Введите **имя бота** (например: `Таро Оракул`)
4. Введите **username бота** (например: `taro_oracle_bot`) — должен заканчиваться на `bot`
5. BotFather выдаст токен вида `1234567890:ABCdef...` — это ваш `TELEGRAM_TOKEN`

**Дополнительная настройка бота:**
```
/setdescription — описание бота
/setabouttext — текст "О боте"
/setuserpic — аватар бота
/setcommands — добавьте: start - Запустить бота, menu - Главное меню
```

---

## 🧠 Получение Groq API ключа

1. Перейдите на [console.groq.com](https://console.groq.com)
2. Зарегистрируйтесь (можно через Google)
3. В левом меню выберите **"API Keys"**
4. Нажмите **"Create API Key"**
5. Дайте ключу имя и скопируйте его → это ваш `GROQ_API_KEY`

> 💡 Groq предоставляет бесплатный доступ к Llama 3.3 70B с лимитом 6000 запросов/минуту — более чем достаточно для бота.

---

## 🚀 Деплой на Railway

### Шаг 1: Подготовить код

Убедитесь, что у вас установлен [Git](https://git-scm.com/).

```bash
cd tarot_bot
git init
git add .
git commit -m "Initial tarot bot"
```

### Шаг 2: Загрузить на GitHub
1. Создайте аккаунт на [github.com](https://github.com)
2. Создайте **новый репозиторий** (кнопка `+` → New repository)
3. Название: `tarot-bot`, тип: **Private** (рекомендуется)
4. Выполните команды из инструкции GitHub:
```bash
git remote add origin https://github.com/ВАШ_USERNAME/tarot-bot.git
git branch -M main
git push -u origin main
```

### Шаг 3: Создать проект на Railway
1. Перейдите на [railway.app](https://railway.app)
2. Войдите через **GitHub**
3. Нажмите **"New Project"**
4. Выберите **"Deploy from GitHub repo"**
5. Выберите ваш репозиторий `tarot-bot`
6. Railway автоматически определит Python-проект

### Шаг 4: Добавить переменные окружения
1. В панели проекта выберите ваш сервис
2. Перейдите на вкладку **"Variables"**
3. Добавьте следующие переменные (нажмите **"New Variable"** для каждой):

| Переменная | Значение |
|-----------|---------|
| `TELEGRAM_TOKEN` | Токен от BotFather |
| `GROQ_API_KEY` | Ключ от Groq Console |
| `SUPABASE_URL` | URL вашего проекта Supabase |
| `SUPABASE_KEY` | Anon-ключ Supabase |

4. После добавления всех переменных Railway автоматически перезапустит деплой

### Шаг 5: Настроить тип сервиса
1. Перейдите на вкладку **"Settings"** вашего сервиса
2. В разделе **"Deploy"** убедитесь, что используется **`Procfile`**
3. Railway использует команду: `python bot.py`

### Шаг 6: Проверить запуск
1. Перейдите на вкладку **"Deployments"**
2. Откройте последний деплой и посмотрите логи
3. Вы должны увидеть:
   ```
   🔮 Таро-бот запущен!
   Планировщик уведомлений запущен (12:00 МСК)
   ```
4. Откройте вашего бота в Telegram и напишите `/start`

---

## 🖥️ Локальный запуск (для разработки)

```bash
# 1. Клонировать репозиторий
git clone https://github.com/ВАШ_USERNAME/tarot-bot.git
cd tarot-bot

# 2. Создать виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Создать файл .env
cp .env.example .env
# Отредактируйте .env и вставьте ваши ключи

# 5. Запустить бота
python bot.py
```

---

## 📋 Переменные окружения

| Переменная | Где получить | Обязательна |
|-----------|-------------|-------------|
| `TELEGRAM_TOKEN` | [@BotFather](https://t.me/BotFather) | ✅ Да |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | ✅ Да |
| `SUPABASE_URL` | Project Settings → API | ✅ Да |
| `SUPABASE_KEY` | Project Settings → API (anon key) | ✅ Да |

---

## 💡 Как добавить реальную оплату (следующий шаг)

В файле `bot.py` найдите обработчик `pay_plan_*` (строка с `elif data.startswith("pay_")`). 
Замените заглушку на интеграцию с:
- **ЮKassa** (YooMoney) — `yookassa` пакет Python
- **Telegram Payments** — встроенная оплата в Telegram
- **Робокасса** — `robokassa` Python SDK

---

## 🔄 Обновление бота

```bash
git add .
git commit -m "Update: описание изменений"
git push origin main
```

Railway автоматически задеплоит новую версию.

---

## ❓ Частые проблемы

**Бот не отвечает:**
- Проверьте логи в Railway → Deployments
- Убедитесь, что `TELEGRAM_TOKEN` верный
- Проверьте, что Procfile содержит: `worker: python bot.py`

**Ошибка Supabase:**
- Проверьте `SUPABASE_URL` и `SUPABASE_KEY`
- Убедитесь, что SQL-схема была применена
- Проверьте политики RLS в Table Editor

**Ошибка Groq:**
- Проверьте `GROQ_API_KEY`
- Убедитесь, что модель `llama-3.3-70b-versatile` доступна в вашем аккаунте

---

## 📞 Поддержка

Если возникли вопросы — обратитесь к разработчику бота.
