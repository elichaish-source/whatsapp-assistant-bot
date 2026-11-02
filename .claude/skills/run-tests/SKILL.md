---
name: run-tests
description: הרצת בדיקות ה-backend על השרת, במכולה חד-פעמית מול בסיס נתונים נפרד. להשתמש לפני כל מיזוג של קוד חדש, אחרי מיזוג של main לענף, או כשהמשתמש מבקש "תריץ את הבדיקות" או "תבדוק שהקוד עובד". נדרש כי במחשב של המשתמש אין Python, Node או Docker.
---

# הרצת הבדיקות

## למה בשרת ולא במחשב
במחשב במשרד אין Python, אין Node ואין Docker. ‏`python -V` מדפיס "Python" בלי גרסה — זה קיצור דרך של חנות Windows ולא מתורגמן. **אי אפשר להריץ שם `pytest`.**

לכן הבדיקות רצות על השרת, אבל **לא על המערכת שרצה**: מכולה חד-פעמית, בסיס נתונים נפרד בשם `assistant_test`, והכול נמחק בסוף. השירותים שרצים לא נוגעים ולא נעצרים, וקוד שלא מוזג לא נפרס.

## ההרצה
1. העלה את הסקריפט והרץ אותו (‏PowerShell, לא Git Bash):
   ```powershell
   scp "<נתיב הסקיל>\run-tests.sh" assistant:/root/run-tests.sh
   ssh assistant bash /root/run-tests.sh <שם הענף>
   ```
   בלי שם ענף הוא בודק את `main`.

2. הסקריפט מדפיס בסוף `EXIT=0` ואת סיכום pytest. **אל תדווח שהבדיקות עברו בלי לראות את שתי השורות האלה.**

3. בסוף הוא מוחק את בסיס הנתונים הזמני ואת הקוד שהוריד. אם הוא נפל באמצע, נקה ידנית:
   ```bash
   ssh assistant "docker exec -i whatsapp-assistant-bot-db-1 psql -U assistant -d assistant -c 'DROP DATABASE IF EXISTS assistant_test'; rm -rf /root/test-run /root/run-tests.sh"
   ```

## מה הבדיקות מכסות
‏`conftest.py` מריץ `alembic downgrade base` ואז `upgrade head` לפני הבדיקות, ולכן **כל מיגרציה חדשה נבדקת בשני הכיוונים** בכל הרצה. זו הדרך לדעת שהמיגרציה לא תשבור את השרת.

## אם בדיקה נכשלת
תקן **בקוד, בענף, ודרך GitHub** — לא על השרת. השרת הוא יעד פריסה ולא סביבת פיתוח.
