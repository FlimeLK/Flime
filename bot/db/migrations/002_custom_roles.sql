CREATE TABLE custom_roles (
    id           BIGSERIAL PRIMARY KEY,
    chat_id      BIGINT NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    team         TEXT NOT NULL DEFAULT 'village',
    ability      TEXT NOT NULL DEFAULT 'none',
    min_players  INTEGER NOT NULL DEFAULT 4,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_by   BIGINT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX custom_roles_chat_name ON custom_roles (chat_id, lower(name));
