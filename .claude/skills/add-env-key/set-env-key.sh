#!/bin/bash
# מוסיף או מעדכן מפתח בקובץ .env בשרת, בלי שהערך מופיע בשורת הפקודה,
# על המסך או בהיסטוריה של המסוף.
#
# שימוש:
#   bash set-env-key.sh NAME              # מבקש את הערך בהסתר
#   bash set-env-key.sh NAME --generate   # מייצר מחרוזת אקראית
set -u
ENV_FILE=/root/whatsapp-assistant-bot/.env
NAME=${1:-}
MODE=${2:-}

if [ -z "$NAME" ]; then
  echo "חסר שם המפתח. למשל: bash set-env-key.sh ANTHROPIC_API_KEY"
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "לא נמצא $ENV_FILE"
  exit 1
fi

if [ "$MODE" = "--generate" ]; then
  VALUE=$(openssl rand -hex 24)
  echo "יוצר מחרוזת אקראית ל-$NAME."
else
  read -r -s -p "הדבק את הערך של $NAME ואז Enter: " VALUE
  echo
fi

if [ -z "$VALUE" ]; then
  echo "לא הוזן ערך. לא שונה כלום."
  exit 1
fi

cp "$ENV_FILE" "$ENV_FILE.bak"
TMP=$(mktemp)
VALUE="$VALUE" awk -v name="$NAME" '
  BEGIN { v = ENVIRON["VALUE"]; found = 0 }
  $0 ~ "^" name "=" { print name "=" v; found = 1; next }
  { print }
  END { if (!found) print name "=" v }
' "$ENV_FILE" > "$TMP"
mv "$TMP" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "נשמר ב-.env. אורך הערך: ${#VALUE} תווים. הערך עצמו לא הוצג."
echo "גיבוי של הקובץ הקודם: $ENV_FILE.bak"
echo "כדי שהשינוי ייכנס לתוקף: cd whatsapp-assistant-bot && sudo docker compose up -d"
