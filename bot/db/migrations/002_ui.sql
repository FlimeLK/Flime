CREATE TABLE emoji_overrides (
    key        TEXT PRIMARY KEY,
    custom_id  TEXT NOT NULL
);

CREATE TABLE media (
    slot     TEXT PRIMARY KEY,
    kind     TEXT NOT NULL CHECK (kind IN ('photo', 'animation', 'video')),
    file_id  TEXT NOT NULL
);
