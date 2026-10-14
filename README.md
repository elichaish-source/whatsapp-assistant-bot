# whatsapp-assistant-bot

עוזר אישי לניהול משימות, לקוחות, מיילים וכספים: בוט וואטסאפ עם דשבורד.
האפיון המלא נמצא ב-[SPEC.md](SPEC.md).

## מה יש עכשיו (שלב 1)

- **דשבורד** בכתובת `https://elichay.duckdns.org`, בעברית, עובד גם בטלפון.
- **כניסה** עם קוד חד-פעמי שנשלח ל"הודעה לעצמי" בוואטסאפ. החיבור נשמר 30 יום.
- **לקוחות**, **פרויקטים** ו**משימות**: הוספה, עריכה וסינון.
- **הגדרות:** עריכת הרשימות של משפחות הלקוחות, התחומים וסוגי המשימה.

### כללי השיוך

- לקוח יכול להיות שייך לכמה משפחות (יעדים, עסק פרטי, נדל"ן).
- לכל פרויקט ולכל משימה חובה לבחור תחום.
- משימה בפרויקט מקבלת את התחום שלו כברירת מחדל, ואפשר לשנות.
- משימה בפרויקט של לקוח משויכת אוטומטית לאותו לקוח. אם מעבירים את הפרויקט ללקוח אחר, גם המשימות עוברות.
- בתחום שמסומן "מחייב לקוח" (בהתחלה רק "לקוחות") אי אפשר לשמור משימה בלי לקוח.
- אי אפשר למחוק לקוח או פרויקט שיש להם משימות או פרויקטים. במקום זה מסמנים אותם כלא פעיל או כהסתיים.

## מבנה

| תיקייה | תפקיד |
|---|---|
| `backend/` | שרת Python (FastAPI) ובסיס הנתונים (PostgreSQL, מיגרציות עם Alembic) |
| `frontend/` | הדשבורד (React + Vite), שמוגש דרך Caddy עם HTTPS אוטומטי |
| `docker-compose.yml` | כל הרכיבים: בסיס נתונים, שרת, WAHA, Caddy ו-DuckDNS |

## התקנה על השרת

השרת הראשי הוא Oracle Cloud בשכבה החינמית (מעבד Arm). Hetzner הוא גיבוי.
ב-Oracle המשתמש בשרת הוא `ubuntu`, וב-Hetzner הוא `root`.

### לפני ההתקנה
- **שרת Ubuntu 24.04** שאפשר להתחבר אליו ב-SSH.
- **פורטים 80 ו-443 פתוחים בלוח הבקרה.**
  - ב-Oracle: ברשת של השרת (VCN) ← Subnet ← Security List ← הוסף כלל Ingress מ-`0.0.0.0/0`, ‏TCP, לפורטים `80,443`.
  - ב-Hetzner: רק אם הגדרת חומת אש.
- **תת-דומיין ב-[DuckDNS](https://www.duckdns.org)** (`elichay`), וה-token של החשבון.

### 1. מפתח פריסה: הרשאת קריאה למאגר
המאגר פרטי, ולכן השרת צריך מפתח משלו. על השרת:
```bash
ssh-keygen -t ed25519 -N "" -C "assistant-server" -f ~/.ssh/github_deploy
printf 'Host github.com\n  IdentityFile ~/.ssh/github_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null
cat ~/.ssh/github_deploy.pub
```
העתק את השורה שהוצגה (מתחילה ב-`ssh-ed25519`). ב-GitHub: המאגר ← **Settings** (הגדרות) ← **Deploy keys** (מפתחות פריסה) ← **Add deploy key** (הוספת מפתח). שם: `server`. הדבק את השורה, **אל תסמן** "Allow write access" (הרשאת כתיבה), ולחץ **Add key**.

### 2. הורדת הקוד והתקנה
```bash
git clone git@github.com:elichaish-source/whatsapp-assistant-bot.git
cd whatsapp-assistant-bot
./scripts/install.sh
```
הסקריפט שואל שתי שאלות: מספר הוואטסאפ וה-token של DuckDNS. כל השאר אוטומטי:
- התקנת Docker ופתיחת פורטים 80 ו-443 על השרת.
- יצירת סיסמאות אקראיות ובחירת גרסת WAHA לפי סוג המעבד.
- הפעלת המערכת וגיבוי יומי של בסיס הנתונים ב-03:15, לפי שעון ישראל.

### 3. חיבור הוואטסאפ (פעם אחת)
- מהמחשב, פתח מנהרה לשרת:
  ```bash
  ssh -L 3000:localhost:3000 ubuntu@<כתובת-השרת>
  ```
- פתח בדפדפן `http://localhost:3000/dashboard`. משתמש: `admin`. את הסיסמה רואים על השרת בפקודה `grep WAHA_ .env`.
- אם הדשבורד של WAHA מבקש מפתח API, הזן את `WAHA_API_KEY` מאותה פקודה.
- בסשן `default`, סרוק את קוד ה-QR מהטלפון: וואטסאפ ← מכשירים מקושרים ← קישור מכשיר.

### 4. כניסה לדשבורד
פתח `https://elichay.duckdns.org`, הזן את המספר שלך, וקבל את הקוד ב"הודעה לעצמי".

### עדכון לגרסה חדשה
```bash
cd ~/whatsapp-assistant-bot && ./scripts/update.sh
```
הסקריפט מוריד את הקוד, מגבה ומפעיל מחדש. המיגרציות של בסיס הנתונים רצות אוטומטית.

### גיבוי ושחזור
- הגיבויים נשמרים ב-`backups/`. נשמרים 14 הגיבויים האחרונים.
- גיבוי ידני: `sudo ./scripts/backup.sh`
- **הגיבויים יושבים על אותו שרת.** אם השרת נמחק, גם הם נמחקים. מדי פעם כדאי להעתיק אותם למחשב:
  ```bash
  scp -r ubuntu@<כתובת-השרת>:whatsapp-assistant-bot/backups .
  ```
- שחזור מגיבוי. ⚠️ **מוחק את כל המידע הנוכחי** ומחליף אותו בתוכן הגיבוי:
  ```bash
  sudo docker compose stop backend
  sudo docker compose exec -T db psql -U assistant assistant -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  gunzip -c backups/<קובץ>.sql.gz | sudo docker compose exec -T db psql -U assistant assistant
  sudo docker compose start backend
  ```

## פיתוח מקומי

```bash
# שרת
cd backend
pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://... OWNER_PHONE=972... COOKIE_SECURE=false
alembic upgrade head
uvicorn app.main:app --reload

# בדיקות (דורש בסיס נתונים PostgreSQL ריק לבדיקות)
TEST_DATABASE_URL=postgresql+psycopg://.../assistant_test pytest

# דשבורד
cd frontend
npm install
npm run dev
```
