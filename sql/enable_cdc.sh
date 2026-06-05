#!/usr/bin/env bash
# Enable CDC on WideWorldImporters (runs sql/enable_cdc.sql inside the sqlserver container).
# Prereq: the container was (re)created with MSSQL_AGENT_ENABLED=true so the capture job runs.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; . ./.env; set +a; fi
SA_PW="${MSSQL_SA_PASSWORD:-Change_me_strong_passw0rd}"

SQLCMD="$(docker compose exec -T sqlserver bash -lc 'ls /opt/mssql-tools*/bin/sqlcmd 2>/dev/null | head -1' | tr -d '\r')"
[ -n "$SQLCMD" ] || { echo "ERROR: sqlcmd not found in the container." >&2; exit 1; }

# Confirm SQL Agent is running (CDC capture needs it).
agent="$(docker compose exec -T sqlserver "$SQLCMD" -S localhost -U sa -P "$SA_PW" -C -h -1 \
    -Q "SET NOCOUNT ON; SELECT status_desc FROM sys.dm_server_services WHERE servicename LIKE '%Agent%';" 2>/dev/null | tr -d '\r' | xargs || true)"
echo ">> SQL Server Agent: ${agent:-unknown}"
case "$agent" in
    *Running*) ;;
    *) echo "WARN: SQL Agent doesn't look Running. CDC change tables won't populate until it is." >&2
       echo "      Ensure the container has MSSQL_AGENT_ENABLED=true, then: docker compose up -d sqlserver" >&2 ;;
esac

echo ">> Enabling CDC ..."
docker compose exec -T sqlserver "$SQLCMD" -S localhost -U sa -P "$SA_PW" -C -b \
    < sql/enable_cdc.sql
echo ">> Done."
