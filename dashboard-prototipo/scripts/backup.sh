#!/usr/bin/env sh
# Backup do PostgreSQL rodando no Docker Compose.
# Uso: ./scripts/backup.sh            -> backups/luz_AAAAMMDD_HHMMSS.dump
#      KEEP=14 ./scripts/backup.sh    -> mantém só os 14 mais recentes
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] && . ./.env
DB="${POSTGRES_DB:-luz}"; USER="${POSTGRES_USER:-luz}"; KEEP="${KEEP:-30}"
mkdir -p backups
OUT="backups/${DB}_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T db pg_dump -U "$USER" -d "$DB" --format=custom --no-owner > "$OUT"
echo "backup gravado em $OUT ($(du -h "$OUT" | cut -f1))"
ls -1t backups/*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm --
