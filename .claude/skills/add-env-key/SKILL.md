---
name: add-env-key
description: הוספה או שינוי של מפתח בקובץ .env בשרת, בלי שהערך עובר בצ'אט. להשתמש כשצריך להגדיר ANTHROPIC_API_KEY, טוקן, סיסמה או כל סוד אחר בשרת, או כשהמשתמש אומר "יש לי את המפתח" או "תגדיר את המפתח".
---

# הגדרת מפתח ב-.env בשרת

**הכלל:** סיסמאות, טוקנים ומפתחות לא עוברים בצ'אט. לא בהודעה של המשתמש ולא בפקודה שמודל מריץ. הם נכנסים ישר לקובץ `.env` על השרת.

## שני מצבים

### א. ערך שאפשר לייצר — עושים את זה לבד
מחרוזות אקראיות (למשל `WAHA_WEBHOOK_HMAC_KEY`, `POSTGRES_PASSWORD`) לא צריכות את המשתמש. מייצרים אותן בשרת, והערך לא עובר בשום מקום:
```bash
ssh assistant "cd whatsapp-assistant-bot && bash /root/set-env-key.sh WAHA_WEBHOOK_HMAC_KEY --generate"
```

### ב. ערך שרק המשתמש יכול להשיג — הוא מדביק אותו בעצמו
‏`ANTHROPIC_API_KEY` ודומיו. **אל תבקש ממנו להדביק את המפתח בצ'אט.** תן לו את הפקודה, והוא יריץ אותה בטרמינל שלו וידביק את הערך בהסתר:

```bash
ssh -t assistant "bash /root/set-env-key.sh ANTHROPIC_API_KEY"
```

הסקריפט מבקש את הערך, לא מציג אותו על המסך, לא שומר אותו בהיסטוריה, ומאשר בסוף רק את **אורך** הערך.

## לפני הכול
צריך להעלות את הסקריפט פעם אחת:
```powershell
scp "<נתיב הסקיל>\set-env-key.sh" assistant:/root/set-env-key.sh
```

## אחרי השינוי
הקונטיינרים קוראים את `.env` רק בהפעלה. לכן:
```bash
ssh assistant "cd whatsapp-assistant-bot && sudo docker compose up -d"
```
ואז הסקיל `server-health`.

## אימות בלי לחשוף
לבדיקה שהמפתח קיים ולא ריק, **בלי להדפיס אותו**:
```bash
ssh assistant "cd whatsapp-assistant-bot && awk -F= '/^ANTHROPIC_API_KEY=/{print \"אורך: \" length(\$2)}' .env"
```
אם זה מחזיר 0 או כלום — המפתח לא הוגדר.

## אזהרה
**אל תריץ `cat .env` ואל תדפיס את תוכנו.** הקובץ מכיל את כל סודות המערכת, והפלט נשמר בתמלול של הסשן.
