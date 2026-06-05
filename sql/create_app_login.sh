#!/usr/bin/env bash
# Create the least-privilege `de_extract` login the pipeline uses (runs create_app_login.sql
# as sa inside the sqlserver container). Re-runnable.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; . ./.env; set +a; fi
SA_PW="${MSSQL_SA_PASSWORD:-Change_me_strong_passw0rd}"
APP_PW="${MSSQL_APP_PASSWORD:-Change_me_app_passw0rd}"

SQLCMD="$(docker compose exec -T sqlserver bash -lc 'ls /opt/mssql-tools*/bin/sqlcmd 2>/dev/null | head -1' | tr -d '\r')"
[ -n "$SQLCMD" ] || { echo "ERROR: sqlcmd not found in the container." >&2; exit 1; }

echo ">> Creating/Updating the de_extract least-privilege login ..."
docker compose exec -T sqlserver "$SQLCMD" -S localhost -U sa -P "$SA_PW" -C -b \
    -v APP_PASSWORD="$APP_PW" \
    < sql/create_app_login.sql
echo ">> Done. The pipeline now connects as de_extract (set MSSQL_APP_PASSWORD in .env to match)."
