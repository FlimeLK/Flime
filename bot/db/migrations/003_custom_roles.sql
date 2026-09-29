CREATE TABLE custom_roles (
    id           SERIAL PRIMARY KEY,
    chat_id      BIGINT NOT NULL,
    name         TEXT NOT NULL,
    emoji        TEXT NOT NULL,
    emoji_id     TEXT,
    description  TEXT NOT NULL DEFAULT '',
    team         TEXT NOT NULL CHECK (team IN ('village', 'evil', 'wolf')),
    ability      TEXT NOT NULL,
    min_players  INTEGER NOT NULL DEFAULT 4,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_by   BIGINT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX custom_roles_chat_idx ON custom_roles (chat_id);
