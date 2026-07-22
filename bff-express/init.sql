CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    role VARCHAR(20) NOT NULL,
    balance DECIMAL(15,2) DEFAULT 0.00
);

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    type VARCHAR(20) NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    counterparty VARCHAR(100),
    status VARCHAR(20) NOT NULL
);

-- Insert dummy data if empty
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM users) THEN
        INSERT INTO users (username, role, balance) VALUES 
        ('anita.rao', 'CUSTOMER', 256400.00),
        ('rohan.kapoor', 'CUSTOMER', 87500.00);
    END IF;
END $$;