CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    role VARCHAR(20) NOT NULL,
    balance DECIMAL(15,2) DEFAULT 0.00
);

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    username VARCHAR(50) NOT NULL,
    type VARCHAR(20) NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    counterparty VARCHAR(100),
    status VARCHAR(20) NOT NULL
);

-- Upgrade databases created by the earlier unscoped BFF initializer.
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS username VARCHAR(50);

-- Owner-scoped recent-history reads and stable timestamp ordering at scale.
CREATE INDEX IF NOT EXISTS idx_transactions_owner_timestamp
    ON transactions (username, timestamp DESC, id DESC);

-- Idempotent demo fixtures; never overwrite balances or role changes on restart.
INSERT INTO users (username, role, balance) VALUES
    ('anita.rao', 'CUSTOMER', 256400.00),
    ('rohan.kapoor', 'CUSTOMER', 87500.00)
ON CONFLICT (username) DO NOTHING;
