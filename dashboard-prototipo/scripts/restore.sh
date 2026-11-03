#!/usr/bin/env sh
# Restaura um backup gerado por backup.sh (SUBSTITUI os dados atuais).
# Uso: ./scripts/restore.sh backups/luz_20261027_120000.dump
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] && . ./.env
FILE="${1:?informe o arquivo .dump}"
DB="${POSTGRES_DB:-luz}"; USER="${POSTGRES_USER:-luz}"
printf "Isto vai substituir o banco '%s'. Continuar? [s/N] " "$DB"; read -r ok; [ "$ok" = "s" ] || exit 1
docker compose stop backend
docker compose exec -T db pg_restore -U "$USER" -d "$DB" --clean --if-exists --no-owner < "$FILE"
docker compose start backend
echo "restauração concluída"
