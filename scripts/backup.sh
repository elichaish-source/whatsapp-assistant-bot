#!/usr/bin/env bash
# גיבוי של בסיס הנתונים לקובץ דחוס. שומר את 14 הגיבויים האחרונים.
set -euo pipefail

KEEP=14
cd "$(dirname "$0")/.."
mkdir -p backups
chmod 700 backups

file="backups/assistant-$(date +%Y-%m-%d_%H%M).sql.gz"
docker compose exec -T db pg_dump -U assistant assistant | gzip > "$file"
chmod 600 "$file"
echo "$(date '+%F %T') נשמר גיבוי: $file"

ls -1t backups/assistant-*.sql.gz | tail -n +$((KEEP + 1)) | xargs -r rm --
