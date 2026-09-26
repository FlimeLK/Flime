CREATE TABLE users (
    id          BIGINT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    username    TEXT,
    shagy       BIGINT NOT NULL DEFAULT 100,
    chervintsi  BIGINT NOT NULL DEFAULT 0,
    vip_until   TIMESTAMPTZ,
    daily_at    TIMESTAMPTZ,
    blocked     BOOLEAN NOT NULL DEFAULT FALSE,
    games       INTEGER NOT NULL DEFAULT 0,
    wins        INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE inventory (
    user_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item     TEXT NOT NULL,
    qty      INTEGER NOT NULL CHECK (qty >= 0),
    PRIMARY KEY (user_id, item)
);

CREATE TABLE purchases (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    product     TEXT NOT NULL,
    stars       INTEGER NOT NULL,
    charge_id   TEXT NOT NULL UNIQUE,
    refunded    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE group_settings (
    chat_id          BIGINT PRIMARY KEY,
    title            TEXT NOT NULL DEFAULT '',
    reg_time         INTEGER NOT NULL DEFAULT 90,
    night_time       INTEGER NOT NULL DEFAULT 60,
    day_time         INTEGER NOT NULL DEFAULT 60,
    vote_time        INTEGER NOT NULL DEFAULT 45,
    confirm_time     INTEGER NOT NULL DEFAULT 30,
    disabled_roles   TEXT[] NOT NULL DEFAULT '{}',
    hide_dead_roles  BOOLEAN NOT NULL DEFAULT FALSE,
    secret_vote      BOOLEAN NOT NULL DEFAULT FALSE,
    items_enabled    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE games (
    chat_id     BIGINT PRIMARY KEY,
    state       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE game_results (
    id          SERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    winner      TEXT NOT NULL,
    players     INTEGER NOT NULL,
    days        INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE game_players (
    game_id  INTEGER NOT NULL REFERENCES game_results(id) ON DELETE CASCADE,
    user_id  BIGINT NOT NULL,
    role     TEXT NOT NULL,
    won      BOOLEAN NOT NULL,
    PRIMARY KEY (game_id, user_id)
);
CREATE INDEX game_players_user_idx ON game_players (user_id);
CREATE INDEX game_results_chat_idx ON game_results (chat_id);

CREATE TABLE promocodes (
    code        TEXT PRIMARY KEY,
    shagy       BIGINT NOT NULL DEFAULT 0,
    chervintsi  BIGINT NOT NULL DEFAULT 0,
    vip_days    INTEGER NOT NULL DEFAULT 0,
    max_uses    INTEGER NOT NULL DEFAULT 1,
    uses        INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE promocode_uses (
    code     TEXT NOT NULL REFERENCES promocodes(code) ON DELETE CASCADE,
    user_id  BIGINT NOT NULL,
    PRIMARY KEY (code, user_id)
);
