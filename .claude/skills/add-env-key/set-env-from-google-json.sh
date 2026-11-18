#!/bin/bash
# שואב את client_id ו-client_secret מקובץ ה-JSON של לקוח ה-OAuth שמורידים
# מ-Google Cloud Console, וכותב אותם אל .env בשרת — בלי להדפיס את הערכים.
#
# למה דרך קובץ ולא בהדבקה: ‏set-env-key.sh מבקש את הערך ב-read -s, שאינו
# מציג דבר בזמן ההקלדה. ‏18.11.2026 זה נראה כמו מסוף תקוע והניסיון נכשל
# בשקט. קובץ JSON עובר ב-scp בלי שאף תו יעבור בצ'אט או בהיסטוריית המסוף.
#
# שימוש:
#   bash set-env-from-google-json.sh /root/google-client.json
#
# בסוף הסקריפט מוחק את קובץ ה-JSON. הוא מכיל את הסוד, ואין סיבה שיישאר.
set -u
ENV_FILE=/root/whatsapp-assistant-bot/.env
JSON=${1:-}

if [ -z "$JSON" ]; then
  echo "חסר נתיב לקובץ ה-JSON. למשל: bash set-env-from-google-json.sh /root/google-client.json"
  exit 1
fi
if [ ! -f "$JSON" ]; then
  echo "לא נמצא הקובץ $JSON"
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "לא נמצא $ENV_FILE"
  exit 1
fi

# שואב ערך של מפתח מתוך ה-JSON. הקובץ של גוגל שטוח, וכל אחד מהמפתחות
# מופיע בו פעם אחת בלבד, ולכן אין צורך במפרש JSON מלא — שאינו מובטח שקיים
# על השרת. הערך אינו מודפס בשום שלב
extract() {
  tr -d '\n\r' < "$JSON" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p"
}

CLIENT_ID=$(extract client_id)
CLIENT_SECRET=$(extract client_secret)

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
  echo "לא נמצאו client_id ו-client_secret בקובץ."
  echo "ודא שזה קובץ ה-JSON של לקוח ה-OAuth (Credentials ← הלקוח ← Download JSON)"
  echo "ולא קובץ של Service account או של מסך האישור. הקובץ לא נמחק."
  exit 1
fi

# בדיקת שפיות על הצורה, בלי להדפיס את הערך. מזהה לקוח של גוגל מסתיים תמיד
# בסיומת הזו, וקובץ מהסוג הלא נכון ייתפס כאן ולא רק בזמן החיבור
case "$CLIENT_ID" in
  *.apps.googleusercontent.com) ;;
  *)
    echo "מזהה הלקוח אינו נגמר ב-.apps.googleusercontent.com — כנראה הקובץ הלא נכון."
    echo "לא שונה כלום, והקובץ לא נמחק."
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

rm -f "$JSON"

echo "נשמר ב-.env. הערכים עצמם לא הוצגו."
echo "  GOOGLE_CLIENT_ID: ${#CLIENT_ID} תווים"
echo "  GOOGLE_CLIENT_SECRET: ${#CLIENT_SECRET} תווים"
echo "קובץ ה-JSON נמחק מהשרת: $JSON"
echo "גיבוי של .env הקודם: $ENV_FILE.bak"
echo "כדי שהשינוי ייכנס לתוקף: cd whatsapp-assistant-bot && sudo docker compose up -d"
