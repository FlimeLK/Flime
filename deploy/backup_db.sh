#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/backups"
mkdir -p "${BACKUP_DIR}"

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-mafia}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-}"

if [[ -z "${DB_PASSWORD}" ]]; then
  echo "DB_PASSWORD is empty. Export DB_PASSWORD first or load .env."
  exit 1
fi

STAMP="$(date +"%Y%m%d_%H%M%S")"
OUT_FILE="${BACKUP_DIR}/mafia_${STAMP}.sql"

export PGPASSWORD="${DB_PASSWORD}"
pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -F p > "${OUT_FILE}"
unset PGPASSWORD

echo "Backup created: ${OUT_FILE}"

