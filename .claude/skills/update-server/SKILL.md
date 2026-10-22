---
name: update-server
description: עדכון השרת לגרסה האחרונה מ-GitHub, עם גיבוי לפני ובדיקה אחרי. להשתמש כשהמשתמש מבקש "תעדכן את השרת", "תעלה את הגרסה החדשה", או אחרי מיזוג של שלב חדש ל-main.
---

# עדכון השרת לגרסה האחרונה

מיועד לסשן מקומי עם חיבור `ssh assistant` שעובד (ראה סקיל `deploy`, שלב 3). בסשן בענן אין גישה לשרת.

## לפני העדכון
1. **בדיקת חיבור:** `ssh -o BatchMode=yes assistant "echo ok"`.
   - אם נכשל: כנראה שהסוכן לא טען את המפתח. תבקש מהמשתמש להריץ בעצמו:
     ```powershell
     ssh-add "$env:USERPROFILE\.ssh\assistant_server"
     ```
2. **מה ייכנס בעדכון:**
   ```bash
   ssh assistant "cd whatsapp-assistant-bot && git fetch -q && git log --oneline HEAD..origin/main"
   ```
   - תציג למשתמש את הרשימה בעברית ותבקש אישור.
   - אם הרשימה ריקה, השרת כבר מעודכן. תעצור כאן.
3. **מיגרציה במבנה הנתונים:** אם יש קבצים חדשים ב-`backend/alembic/versions/`, תגיד את זה למשתמש. הגיבוי שרץ לפני העדכון מאפשר לחזור אחורה.

## העדכון
```bash
ssh assistant "cd whatsapp-assistant-bot && ./scripts/update.sh"
```
הסקריפט מוריד את הקוד, מגבה את בסיס הנתונים, בונה ומפעיל מחדש.

## אחרי העדכון
- תריץ את הסקיל `server-health`.
- **אם משהו נכשל:** תציג את הלוגים ואל תנסה לתקן על השרת עצמו. התיקון נעשה בקוד, דרך GitHub.
  ```bash
  ssh assistant "cd whatsapp-assistant-bot && sudo docker compose logs --tail 100 backend"
  ```
- **חזרה לגרסה הקודמת**, באישור המשתמש בלבד:
  ```bash
  ssh assistant "cd whatsapp-assistant-bot && git reset --hard ORIG_HEAD && sudo docker compose up -d --build"
  ```
  אם הייתה מיגרציה, צריך גם לשחזר את בסיס הנתונים מהגיבוי האחרון. ההוראות ב-README, בסעיף "גיבוי ושחזור".
