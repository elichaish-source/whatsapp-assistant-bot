#!/bin/bash
# מגדיר את GOOGLE_CLIENT_ID ו-GOOGLE_CLIENT_SECRET ב-.env בשרת.
#
# מזהה הלקוח אינו סוד והוא מופיע גלוי בקונסולה ובכתובת הדפדפן, ולכן הוא
# עובר כארגומנט. הסוד עובר בקובץ בלבד, ואינו מופיע בשורת הפקודה, על
# המסך או בתמלול של הסשן.
#
# שימוש:
#   bash set-google-oauth.sh <client_id> /root/gsecret.txt
#
# את קובץ הסוד יוצרים מהמחשב, בלי שהערך יעבור דרך המודל — לוחצים על
# "Copy to clipboard" ליד הסוד בקונסולה, ואז ב-PowerShell:
#   Get-Clipboard | ssh assistant "tr -cd 'A-Za-z0-9_-' > /root/gsecret.txt"
# ⚠️ ‏tr -cd נדרש: ‏PowerShell 5.1 מוסיף BOM של שלושה בתים בתחילת הצינור,
# ו-tr -d '\r\n' לבדו משאיר אותו בקובץ.
#
# בסוף הסקריפט מוחק את קובץ הסוד.
set -u
ENV_FILE=/root/whatsapp-assistant-bot/.env
CLIENT_ID=${1:-}
SECRET_FILE=${2:-}

if [ -z "$CLIENT_ID" ] || [ -z "$SECRET_FILE" ]; then
  echo "שימוש: bash set-google-oauth.sh <client_id> <נתיב לקובץ הסוד>"
  exit 1
fi
if [ ! -f "$SECRET_FILE" ]; then
  echo "לא נמצא קובץ הסוד $SECRET_FILE"
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "לא נמצא $ENV_FILE"
  exit 1
fi

CLIENT_SECRET=$(cat "$SECRET_FILE")

# בדיקות שפיות על הצורה, בלי להדפיס את הערכים. קובץ או הדבקה מהסוג הלא
# נכון נתפסים כאן ולא רק בזמן החיבור, כשהשגיאה מגיעה מגוגל ולא מובנת
case "$CLIENT_ID" in
  *.apps.googleusercontent.com) ;;
  *)
    echo "מזהה הלקוח אינו נגמר ב-.apps.googleusercontent.com. לא שונה כלום."
    exit 1
    ;;
esac
case "$CLIENT_SECRET" in
  GOCSPX-*) ;;
  *)
    echo "הסוד אינו מתחיל ב-GOCSPX-. כנראה הועתק הערך הלא נכון. לא שונה כלום."
    exit 1
    ;;
esac

cp "$ENV_FILE" "$ENV_FILE.bak"

# כותב מפתח אל .env: מחליף שורה קיימת, או מוסיף בסוף אם אינה קיימת.
# הערך עובר דרך משתנה סביבה ולא דרך שורת הפקודה של awk, כדי שלא יופיע
# ב-ps ולא יפורש כתו מיוחד
set_key() {
  local name=$1 value=$2 tmp
  tmp=$(mktemp)
  VALUE="$value" awk -v name="$name" '
    BEGIN { v = ENVIRON["VALUE"]; found = 0 }
    $0 ~ "^" name "=" { print name "=" v; found = 1; next }
    { print }
    END { if (!found) print name "=" v }
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

set_key GOOGLE_CLIENT_ID "$CLIENT_ID"
set_key GOOGLE_CLIENT_SECRET "$CLIENT_SECRET"
chmod 600 "$ENV_FILE"

rm -f "$SECRET_FILE"

echo "נשמר ב-.env. הסוד עצמו לא הוצג."
echo "  GOOGLE_CLIENT_ID: ${#CLIENT_ID} תווים"
echo "  GOOGLE_CLIENT_SECRET: ${#CLIENT_SECRET} תווים"
echo "קובץ הסוד נמחק: $SECRET_FILE"
echo "גיבוי של .env הקודם: $ENV_FILE.bak"
echo "כדי שהשינוי ייכנס לתוקף: cd whatsapp-assistant-bot && sudo docker compose up -d"
