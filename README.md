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

## התקנה על השרת (Hetzner)

1. **התקן Docker** על השרת:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
2. **הורד את הקוד:**
   ```bash
   git clone https://github.com/elichaish-source/whatsapp-assistant-bot.git
   cd whatsapp-assistant-bot
   ```
3. **DuckDNS:** היכנס ל-[duckdns.org](https://www.duckdns.org), ודא שהתת-דומיין `elichay` קיים, והעתק את ה-token.
4. **צור קובץ הגדרות:**
   ```bash
   cp .env.example .env
   nano .env
   ```
   מלא את המספר שלך, את ה-token של DuckDNS ושלוש סיסמאות אקראיות. אפשר ליצור סיסמה כזו עם `openssl rand -hex 24`.
5. **פתח פורטים** 80 ו-443 בחומת האש של Hetzner, אם הגדרת חומת אש.
6. **הרץ:**
   ```bash
   docker compose up -d --build
   ```
7. **חבר את הוואטסאפ (פעם אחת):**
   - מהמחשב שלך, פתח מנהרה לשרת:
     ```bash
     ssh -L 3000:localhost:3000 root@<כתובת-השרת>
     ```
   - פתח בדפדפן `http://localhost:3000/dashboard` והתחבר עם המשתמש `admin` והסיסמה `WAHA_DASHBOARD_PASSWORD`.
   - אם הדשבורד של WAHA מבקש מפתח API, הזן את `WAHA_API_KEY`.
   - בסשן `default`, סרוק את קוד ה-QR מהטלפון: וואטסאפ ← מכשירים מקושרים ← קישור מכשיר.
8. **היכנס לדשבורד:** פתח `https://elichay.duckdns.org`, הזן את המספר שלך, וקבל את הקוד ב"הודעה לעצמי".

### עדכון לגרסה חדשה

```bash
git pull
docker compose up -d --build
```

המיגרציות של בסיס הנתונים רצות אוטומטית כשהשרת עולה.

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
