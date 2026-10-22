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
   ssh assistant 'cd whatsapp-assistant-bot && curl -s -H "X-Api-Key: $(grep ^WAHA_API_KEY= .env | cut -d= -f2)" localhost:3000/api/sessions/default'
   ```
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

## כשמשהו לא תקין
- **רכיב לא רץ:** `ssh assistant "cd whatsapp-assistant-bot && sudo docker compose logs --tail 80 <שם-הרכיב>"`
- **וואטסאפ לא מחובר** (`SCAN_QR_CODE` או `FAILED`): צריך לסרוק QR מחדש. ההוראות בסקיל `deploy`, שלב 7.
- **הדשבורד לא עונה, אבל הרכיבים רצים:**
  - לבדוק שהדומיין מצביע לשרת: `nslookup elichay.duckdns.org`. התשובה צריכה להיות כתובת השרת.
  - לבדוק שפורטים 80 ו-443 פתוחים בלוח הבקרה של הענן.
- **אין גיבוי טרי:** `ssh assistant "tail -20 /var/log/assistant-backup.log"`
- **בשרת Oracle:** אם השרת עצמו לא זמין, ייתכן ש-Oracle עצרה אותו כי היה "לא פעיל" לאורך זמן. בודקים בלוח הבקרה: Compute ← Instances.

תסכם למשתמש בעברית פשוטה: מה תקין, מה לא, ומה אתה מציע לעשות. לא לתקן כלום בלי אישור.
