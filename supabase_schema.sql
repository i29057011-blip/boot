-- ====================================================
-- Таро-бот — схема базы данных Supabase
-- ====================================================

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    telegram_id         BIGINT UNIQUE NOT NULL,
    username            TEXT,
    first_name          TEXT,
    requests_left       INTEGER NOT NULL DEFAULT 0,
    subscription_plan   TEXT,
    card_of_day_date    DATE,
    card_of_day_card    TEXT,
    card_of_day_pending JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);

-- Автообновление updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ====================================================
-- Таблица pending_payments (ЮKassa)
-- ====================================================
CREATE TABLE IF NOT EXISTS pending_payments (
    id          BIGSERIAL PRIMARY KEY,
    payment_id  TEXT UNIQUE NOT NULL,   -- UUID от ЮKassa
    telegram_id BIGINT NOT NULL,
    plan_label  TEXT NOT NULL,
    processed   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pending_payments_payment_id ON pending_payments(payment_id);
CREATE INDEX IF NOT EXISTS idx_pending_payments_telegram_id ON pending_payments(telegram_id);

-- ====================================================
-- RLS (Row Level Security)
-- ====================================================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access users" ON users FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE pending_payments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access payments" ON pending_payments FOR ALL USING (true) WITH CHECK (true);

-- ====================================================
-- История раскладов (опционально)
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
ALTER TABLE spread_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access spread_history" ON spread_history FOR ALL USING (true) WITH CHECK (true);
