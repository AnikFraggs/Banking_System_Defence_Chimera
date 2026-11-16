-- Engineering tables for idempotency, the transactional outbox, and saga instances.
-- Idempotent so it coexists with Hibernate ddl-auto=update on the legacy entities.
-- ANSI types keep it usable on PostgreSQL and H2.

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id            VARCHAR(128) PRIMARY KEY,
    scope         VARCHAR(64)  NOT NULL,
    request_hash  VARCHAR(64)  NOT NULL,
    status        VARCHAR(16)  NOT NULL,
    response_json TEXT,
    created_at    TIMESTAMP    NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_events (
    id             UUID         PRIMARY KEY,
    aggregate_type VARCHAR(64)  NOT NULL,
    aggregate_id   UUID         NOT NULL,
    event_type     VARCHAR(64)  NOT NULL,
    payload        TEXT         NOT NULL,
    status         VARCHAR(16)  NOT NULL,
    attempts       INT          NOT NULL,
    last_error     VARCHAR(500),
    created_at     TIMESTAMP    NOT NULL,
    published_at   TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_outbox_status_created ON outbox_events (status, created_at);
CREATE INDEX IF NOT EXISTS idx_outbox_aggregate ON outbox_events (aggregate_id);

CREATE TABLE IF NOT EXISTS saga_instances (
    id           UUID         PRIMARY KEY,
    order_id     UUID         NOT NULL,
    type         VARCHAR(64)  NOT NULL,
    status       VARCHAR(16)  NOT NULL,
    current_step VARCHAR(64),
    last_error   VARCHAR(500),
    created_at   TIMESTAMP    NOT NULL,
    updated_at   TIMESTAMP    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_saga_order ON saga_instances (order_id);