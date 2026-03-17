-- ====================================================
-- Таро-бот — схема базы данных Supabase
-- Выполните этот SQL в Supabase SQL Editor
-- ====================================================

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    telegram_id         BIGINT UNIQUE NOT NULL,
    username            TEXT,
    first_name          TEXT,

    -- Подписка
    requests_left       INTEGER NOT NULL DEFAULT 0,
    subscription_plan   TEXT,

    -- Карта дня
    card_of_day_date    DATE,
    card_of_day_card    TEXT,
    card_of_day_pending JSONB,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Индекс для быстрого поиска по telegram_id
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);

-- Триггер: автоматически обновлять updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ====================================================
-- Политики безопасности (Row Level Security)
-- ====================================================

-- Включить RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Разрешить серверному ключу полный доступ (service_role)
CREATE POLICY "Service role full access" ON users
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ====================================================
-- Таблица истории раскладов (опционально)
-- ====================================================
CREATE TABLE IF NOT EXISTS spread_history (
    id              BIGSERIAL PRIMARY KEY,
    telegram_id     BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    spread_type     TEXT NOT NULL,
    question        TEXT NOT NULL,
    cards           JSONB NOT NULL,
    interpretation  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spread_history_telegram_id ON spread_history(telegram_id);

ALTER TABLE spread_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access spread_history" ON spread_history
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ====================================================
-- Проверка: просмотр созданных таблиц
-- ====================================================
-- SELECT * FROM users LIMIT 10;
-- SELECT * FROM spread_history LIMIT 10;
