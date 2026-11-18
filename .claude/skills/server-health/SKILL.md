---
name: server-health
description: בדיקת מצב השרת - שכל הרכיבים רצים, שהדשבורד עונה ב-HTTPS, שוואטסאפ מחובר, שיש גיבויים טריים ושיש מקום בדיסק ובזיכרון. להשתמש כשהמשתמש שואל "השרת עובד?", "מה מצב השרת", "הבוט לא עונה", או אחרי התקנה ועדכון.
---

# בדיקת מצב השרת

מיועד לסשן מקומי עם חיבור `ssh assistant` שעובד. הבדיקות קוראות מידע בלבד ולא משנות שום דבר.

## הבדיקות
תריץ את כולן. בסוף תסכם בטבלה, עם ✅ או ❌ ליד כל בדיקה.

1. **רכיבים רצים.** תקין כשכל חמשת הרכיבים (db, ‏backend, ‏waha, ‏caddy, ‏duckdns) במצב `running`:
   ```bash
   ssh assistant "cd whatsapp-assistant-bot && sudo docker compose ps --format '{{.Service}} {{.State}}'"
   ```
2. **הדשבורד עונה.** מריצים מהמחשב המקומי. תקין כשהתשובה היא `{"ok":true}`:
   ```bash
   curl -s https://elichay.duckdns.org/api/health
   ```
3. **וואטסאפ מחובר.** תקין כשהשדה `status` הוא `WORKING`. המפתח נקרא מהקובץ ישירות על השרת, ולא מודפס:
   ```bash
   ssh assistant 'cd whatsapp-assistant-bot && curl -s -H "X-Api-Key: $(grep ^WAHA_API_KEY= .env | cut -d= -f2- | tr -d "\r\n")" localhost:3000/api/sessions/default'
   ```
   ⚠️ **`-f2-` ולא `-f2`.** ‏18.11.2026 הבדיקה החזירה `401 Unauthorized` אף שוואטסאפ היה מחובר: המפתח עצמו מכיל `=`, ו-`-f2` חתך אותו באמצע. עם `-f2-` המפתח יוצא במלואו (48 תווים) והתשובה `WORKING`. **‏401 כאן אינו בהכרח ניתוק — קודם לוודא שהמפתח לא נחתך.**
4. **גיבוי טרי.** תקין כשיש קובץ מ-24 השעות האחרונות:
   ```bash
   ssh assistant "ls -lt whatsapp-assistant-bot/backups | head -3"
   ```
5. **דיסק.** תקין כשפחות מ-80% בשימוש:
   ```bash
   ssh assistant "df -h /"
   ```
6. **זיכרון.** תקין כשיש זיכרון פנוי (`available`):
   ```bash
   ssh assistant "free -h"
   ```
7. **החיבור לגוגל** (משלב 4-1). תקין כש-`status` הוא `connected` ו-`last_checked_at` מהיממה האחרונה. **אפס שורות אינו תקלה** — פירושו שגוגל עוד לא חוברה:
   ```bash
   ssh assistant 'cd whatsapp-assistant-bot && sudo docker compose exec -T db psql -U assistant -d assistant -x -c "SELECT status, email, last_checked_at, left(last_error, 80) AS last_error FROM google_credentials"'
   ```

## כשמשהו לא תקין
- **רכיב לא רץ:** `ssh assistant "cd whatsapp-assistant-bot && sudo docker compose logs --tail 80 <שם-הרכיב>"`
- **וואטסאפ לא מחובר** (`SCAN_QR_CODE` או `FAILED`): צריך לסרוק QR מחדש. ההוראות בסקיל `deploy`, שלב 7.
- **הדשבורד לא עונה, אבל הרכיבים רצים:**
  - לבדוק שהדומיין מצביע לשרת: `nslookup elichay.duckdns.org`. התשובה צריכה להיות כתובת השרת.
  - לבדוק שפורטים 80 ו-443 פתוחים בלוח הבקרה של הענן.
- **אין גיבוי טרי:** `ssh assistant "tail -20 /var/log/assistant-backup.log"`
- **גוגל `disconnected`:** `last_error` אומר למה. ברוב המקרים (ביטול גישה, החלפת סיסמת הגוגל) הפתרון הוא חיבור מחדש בדשבורד ← הגדרות ← חיבור לגוגל. ⚠️ **אם הכתוב הוא שפענוח נכשל — `GOOGLE_TOKEN_KEY` ב-`.env` שונה**, ואז חיבור מחדש הוא הדרך היחידה; אין גיבוי לטוקן.
- **גוגל `connected` אבל `last_checked_at` ישן מיממה:** לולאת התזכורות לא רצה. לבדוק ש-`WAHA_WEBHOOK_HMAC_KEY` מוגדר, ואת `sudo docker compose logs --tail 50 backend`.
- **בשרת Oracle:** אם השרת עצמו לא זמין, ייתכן ש-Oracle עצרה אותו כי היה "לא פעיל" לאורך זמן. בודקים בלוח הבקרה: Compute ← Instances.

תסכם למשתמש בעברית פשוטה: מה תקין, מה לא, ומה אתה מציע לעשות. לא לתקן כלום בלי אישור.
