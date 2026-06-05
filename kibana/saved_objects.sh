#!/usr/bin/env bash
# Export / import Kibana saved objects (data views, visualizations, dashboards) as NDJSON,
# so they're version-controlled and reproducible instead of re-clicked after a reset.
#
#   ./kibana/saved_objects.sh export   -> writes kibana/saved_objects.ndjson (commit this)
#   ./kibana/saved_objects.sh import   -> loads kibana/saved_objects.ndjson (overwrite=true)
#
# Saved objects live in Elasticsearch's .kibana indices; this just snapshots them to a file.
# Security is disabled locally, so no auth — only the kbn-xsrf header Kibana requires on POST.
set -euo pipefail
cd "$(dirname "$0")/.."

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
FILE="kibana/saved_objects.ndjson"
# excludeExportDetails=true keeps the trailing summary line out, so the file re-imports cleanly.
TYPES='["index-pattern","search","visualization","lens","dashboard","map"]'

wait_for_kibana() {
    echo ">> Waiting for Kibana at $KIBANA_URL ..."
    for _ in $(seq 1 30); do
        code="$(curl -s -o /dev/null -w '%{http_code}' "$KIBANA_URL/api/status" || true)"
        if [ "$code" = "200" ]; then
            echo "   ready."
            return 0
        fi
        sleep 2
    done
    echo "ERROR: Kibana not ready at $KIBANA_URL (is 'make up-serve' running?)" >&2
    exit 1
}

case "${1:-}" in
    export)
        wait_for_kibana
        echo ">> Exporting saved objects -> $FILE"
        http="$(curl -s -w '%{http_code}' -o "$FILE" \
            -X POST "$KIBANA_URL/api/saved_objects/_export" \
            -H "kbn-xsrf: true" -H "Content-Type: application/json" \
            -d "{\"type\": $TYPES, \"includeReferencesDeep\": true, \"excludeExportDetails\": true}")"
        if [ "$http" != "200" ]; then
            echo "ERROR: export failed (HTTP $http):" >&2
            cat "$FILE" >&2
            exit 1
        fi
        echo ">> Wrote $(grep -c '' "$FILE" || echo 0) object(s) to $FILE"
        ;;
    import)
        [ -f "$FILE" ] || { echo "ERROR: $FILE not found — run 'make kibana-export' first." >&2; exit 1; }
        wait_for_kibana
        echo ">> Importing $FILE (overwrite) ..."
        curl -s -X POST "$KIBANA_URL/api/saved_objects/_import?overwrite=true" \
            -H "kbn-xsrf: true" \
            --form file=@"$FILE" | python3 -m json.tool
        ;;
    *)
        echo "usage: $0 export|import" >&2
        exit 1
        ;;
esac
