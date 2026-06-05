#!/usr/bin/env bash
# Restore the WideWorldImporters sample databases into the running SQL Server container.
#
#   WideWorldImporters    -> OLTP source for the pipeline (Phase 1 extracts from this)
#   WideWorldImportersDW  -> star-schema warehouse, REFERENCE only (the "answer key")
#
# Prereqs: `make up-ingest` (container running) and the .bak files in data/backups/.
# Re-runnable: uses WITH REPLACE, so running twice just overwrites.
set -euo pipefail

# Run from repo root regardless of where this is called from.
cd "$(dirname "$0")/.."

BACKUP_DIR="data/backups"
CONTAINER_BACKUP_DIR="/var/opt/mssql/backups"

# Load .env if present so we use the same SA password as the container.
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi
SA_PW="${MSSQL_SA_PASSWORD:-Change_me_strong_passw0rd}"

# Map: database name -> backup filename
DBS=(
    "WideWorldImporters:WideWorldImporters-Full.bak"
    "WideWorldImportersDW:WideWorldImportersDW-Full.bak"
)

echo ">> Checking the sqlserver container is up..."
if ! docker compose ps sqlserver 2>/dev/null | grep -Eq "Up|running"; then
    echo "ERROR: sqlserver isn't running. Start it first:  make up-ingest" >&2
    exit 1
fi

echo ">> Locating sqlcmd inside the container..."
SQLCMD=$(docker compose exec -T sqlserver bash -lc 'ls /opt/mssql-tools*/bin/sqlcmd 2>/dev/null | head -1' | tr -d '\r')
if [ -z "$SQLCMD" ]; then
    echo "ERROR: sqlcmd not found in the container image." >&2
    exit 1
fi
echo "   using $SQLCMD"

# Container "Up" != SQL Server ready. Under Rosetta, first boot can take ~30-90s.
# Poll until the server actually answers before we try to restore.
echo ">> Waiting for SQL Server to accept connections (slow under Rosetta, be patient)..."
ready=""
for i in $(seq 1 40); do
    if docker compose exec -T sqlserver "$SQLCMD" \
        -S localhost -U sa -P "$SA_PW" -C -Q "SELECT 1" >/dev/null 2>&1; then
        ready="yes"
        echo "   ready after ~$(( (i - 1) * 3 ))s."
        break
    fi
    sleep 3
done
if [ -z "$ready" ]; then
    echo "ERROR: SQL Server didn't accept connections within ~2 min." >&2
    echo "       Check it's healthy / not crash-looping:  docker compose logs --tail=50 sqlserver" >&2
    echo "       Also confirm MSSQL_SA_PASSWORD matches the running container (a stale" >&2
    echo "       mssql-data volume keeps the password from FIRST boot; 'make nuke' resets it)." >&2
    exit 1
fi

docker compose exec -T --user root sqlserver mkdir -p "$CONTAINER_BACKUP_DIR"

for entry in "${DBS[@]}"; do
    db="${entry%%:*}"
    bak="${entry##*:}"

    if [ ! -f "$BACKUP_DIR/$bak" ]; then
        echo "WARN: $BACKUP_DIR/$bak not found — skipping $db." >&2
        continue
    fi

    echo ">> Copying $bak into the container..."
    docker compose cp "$BACKUP_DIR/$bak" "sqlserver:$CONTAINER_BACKUP_DIR/$bak"

    # docker cp lands the file as root with the host's restrictive perms; the SQL Server
    # process runs as the non-root 'mssql' user and needs read + dir-traverse access,
    # else: "Cannot open backup device ... Operating system error 5 (Access is denied)".
    docker compose exec -T --user root sqlserver chmod -R a+rX "$CONTAINER_BACKUP_DIR"

    echo ">> Restoring $db ..."
    docker compose exec -T sqlserver "$SQLCMD" \
        -S localhost -U sa -P "$SA_PW" -C -b \
        -v DBNAME="$db" BAKFILE="$CONTAINER_BACKUP_DIR/$bak" \
        < sql/restore.sql
    echo ">> $db restored."
done

echo ">> Databases now on the server:"
docker compose exec -T sqlserver "$SQLCMD" -S localhost -U sa -P "$SA_PW" -C -b \
    -Q "SET NOCOUNT ON; SELECT name, state_desc FROM sys.databases WHERE database_id > 4 ORDER BY name;"

echo ">> Done."
