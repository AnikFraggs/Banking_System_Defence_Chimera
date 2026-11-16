CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash   VARCHAR(64)  PRIMARY KEY,
    username     VARCHAR(128) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    role         VARCHAR(32)  NOT NULL,
    expires_at   TIMESTAMP    NOT NULL,
    created_at   TIMESTAMP    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions (expires_at);
