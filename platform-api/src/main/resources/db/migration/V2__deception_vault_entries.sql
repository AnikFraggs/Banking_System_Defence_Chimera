-- Deception vault quarantine store with AES-256-GCM envelope encryption.
-- Isolates compromised session snapshots away from production working sets.

CREATE TABLE IF NOT EXISTS deception_vault_entries (
    vault_id            VARCHAR(128) PRIMARY KEY,
    correlation_id      VARCHAR(128) NOT NULL,
    quarantined_at      TIMESTAMP    NOT NULL,
    reason              VARCHAR(500) NOT NULL,
    encrypted_snapshot  TEXT         NOT NULL,
    status              VARCHAR(32)  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vault_correlation ON deception_vault_entries (correlation_id);
