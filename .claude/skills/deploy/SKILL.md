---
name: deploy
description: התקנת המערכת על שרת חדש מההתחלה ועד הסוף (Oracle Cloud או Hetzner), מסשן מקומי במחשב Windows של המשתמש. להשתמש כשהמשתמש מבקש "תתקין על השרת", "פריסה", "שרת חדש", "deploy", או כשממשיכים את ההתקנה ממקום שבו נעצרה.
---

# התקנת המערכת על שרת חדש

הסקיל הזה מיועד ל**סשן מקומי** שרץ על המחשב של המשתמש (Windows, ‏PowerShell). בסשן בענן אין גישה לשרת ולדפדפן. במקרה כזה, תגיד את זה למשתמש ותציע לו לעבור לסשן מקומי.

## כללים
- **הכול בעברית.** לפני כל שלב, תסביר מה הולך לקרות ותבקש אישור.
- **בדיקת המצב הנוכחי:** תקרא את הסעיף "מצב ההתקנה" ב-`CLAUDE.md` ותמשיך מהשלב שבו נעצרו. בסוף כל שלב, תעדכן את הסעיף.
- **סודות לא עוברים דרכך:** סיסמאות, ה-token של DuckDNS, מספר כרטיס אשראי, וסיסמת המפתח. את השלבים שדורשים אותם המשתמש עושה בעצמו, בחלון PowerShell שלו או בדפדפן.
- **דברים שרק המשתמש עושה:** הרשמה לחשבונות, כרטיס אשראי, אימות זהות, הקלדת סיסמאות, וסריקת QR.
- **צילומי מסך:** לפני שאתה מצלם מסך, תוודא שלא רואים בו token או סיסמה.

## שלב 1: חשבון ושרת בענן

**Oracle (ראשי):** אזור בית **Israel Central (Jerusalem)**.
- **סוג השרת (Shape):** ‏`VM.Standard.A1.Flex`, עם 2 מעבדים (OCPU) ו-12GB זיכרון, ‏Ubuntu 24.04. חייב להופיע הכיתוב **Always Free-eligible**.
- **רשת:** VCN חדשה, תת-רשת ציבורית, וכתובת IPv4 ציבורית.
- **פורטים:** ב-Security List של תת-הרשת, תוסיף כלל Ingress מ-`0.0.0.0/0`, ‏TCP, לפורטים `80,443`.

**Hetzner (גיבוי):** ‏Ubuntu 24.04, ‏x86, ‏Shared vCPU, עם 2 מעבדים ו-4GB זיכרון. מיקום: Falkenstein או Nuremberg.

עם התוסף של Chrome מותר לך לנווט בלוח הבקרה ולמלא שדות שאינם סודיים. לפני לחיצה על **Create**, תציג למשתמש את כל הבחירות ותקבל אישור.

## שלב 2: מפתח כניסה במחשב הנוכחי
```powershell
Test-Path "$env:USERPROFILE\.ssh\assistant_server"
```
**אם אין מפתח:** תבקש מהמשתמש להריץ **בחלון PowerShell שלו**, כי הפקודה שואלת על סיסמה:
```powershell
ssh-keygen -t ed25519 -C "assistant-server" -f "$env:USERPROFILE\.ssh\assistant_server"
```
⚠️ **לא לדרוס** מפתח `id_ed25519` קיים. ייתכן שמשהו אחר משתמש בו.

את המפתח הציבורי (`assistant_server.pub`) מדביקים בלוח הבקרה כשיוצרים את השרת. אם השרת כבר קיים, משתמשים בסקיל `add-ssh-key`.

## שלב 3: הגדרת חיבור קבוע
תוסיף את השרת לקובץ `%USERPROFILE%\.ssh\config`, כך שכל פקודה בהמשך תהיה פשוט `ssh assistant`:
```
Host assistant
  HostName <כתובת-IP>
  User ubuntu
  IdentityFile ~/.ssh/assistant_server
  ServerAliveInterval 30
```
ב-Hetzner המשתמש הוא `root`, לא `ubuntu`.

**סוכן מפתחות (ssh-agent):** כדי שתוכל להריץ פקודות `ssh` בלי שהמשתמש יקליד סיסמה בכל פעם, המשתמש מפעיל את הסוכן פעם אחת. הוא מריץ ב-**PowerShell כמנהל** (לחיצה ימנית על PowerShell ← הפעל כמנהל):
```powershell
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent
```
ואחר כך, ב-PowerShell רגיל:
```powershell
ssh-add "$env:USERPROFILE\.ssh\assistant_server"
```
**בדיקה:** `ssh -o BatchMode=yes assistant "echo ok"` אמור להחזיר `ok`.

## שלב 4: מפתח פריסה (גישה לקוד ב-GitHub)
המאגר פרטי. על השרת:
```bash
ssh assistant 'test -f ~/.ssh/github_deploy || ssh-keygen -t ed25519 -N "" -C assistant-server -f ~/.ssh/github_deploy; grep -q github_deploy ~/.ssh/config 2>/dev/null || printf "Host github.com\n  IdentityFile ~/.ssh/github_deploy\n  IdentitiesOnly yes\n" >> ~/.ssh/config; ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null; cat ~/.ssh/github_deploy.pub'
```
את המפתח הציבורי שמודפס מוסיפים ב-GitHub: המאגר ← **Settings** ← **Deploy keys** ← **Add deploy key**.
- שם: `server`.
- **בלי** הרשאת כתיבה ("Allow write access" לא מסומן).

אפשר לעשות את זה דרך Chrome, באישור המשתמש.

## שלב 5: הורדת הקוד
```bash
ssh assistant 'test -d whatsapp-assistant-bot || git clone git@github.com:elichaish-source/whatsapp-assistant-bot.git'
```

## שלב 6: התקנה (המשתמש מריץ)
הסקריפט שואל על מספר הוואטסאפ ועל ה-token של DuckDNS. לכן **המשתמש מריץ אותו בחלון PowerShell שלו**, ולא אתה:
```powershell
ssh -t assistant "cd whatsapp-assistant-bot && ./scripts/install.sh"
```
- ההודעות של הסקריפט בעברית, ובטרמינל של Windows הן עלולות להופיע הפוכות. תסביר מראש את שתי השאלות:
  1. מספר הוואטסאפ.
  2. ה-token, שמעתיקים מאתר DuckDNS. הוא לא מוצג בזמן ההדבקה.
- לפני ההרצה: ב-[duckdns.org](https://www.duckdns.org) הדומיין `elichay` כבר קיים. הכתובת שלו תתעדכן לבד.
- אם הסקריפט נכשל, תקרא את הלוגים: `ssh assistant "cd whatsapp-assistant-bot && sudo docker compose logs --tail 100"`

## שלב 7: חיבור וואטסאפ
המנוע הוא GOWS, שלא מפעיל דפדפן. אין צורך במנהרת SSH ולא בדשבורד של WAHA.

⚠️ **חלון ההתחברות נסגר אחרי כדקה וחצי**, ואז הסשן עובר ל-`FAILED`. לכן **קודם מוודאים שהמשתמש מוכן, ורק אחר כך מאתחלים ומייצרים.**

1. תבקש מהמשתמש לפתוח בטלפון: וואטסאפ ← הגדרות ← **מכשירים מקושרים** ← **קישור מכשיר**, ולהישאר שם עם המצלמה פתוחה. אם הוא כבר היה שם — שיצא ויחזור, כדי שהמסך יהיה טרי. **תחכה שיגיד שהוא מוכן.**
2. רק אז, תריץ סקריפט שמאתחל את הסשן ושומר QR טרי (לפי התבנית של `scp` + `ssh assistant bash /root/x.sh`):
   ```bash
   KEY=$(grep ^WAHA_API_KEY= .env | cut -d= -f2)
   curl -s -X POST -H "X-Api-Key: $KEY" localhost:3000/api/sessions/default/stop > /dev/null
   sleep 3
   curl -s -X POST -H "X-Api-Key: $KEY" localhost:3000/api/sessions/default/start > /dev/null
   # להמתין עד שהמצב הוא SCAN_QR_CODE, ואז:
   curl -s -o /root/qr.png -H "X-Api-Key: $KEY" "localhost:3000/api/default/auth/qr?format=image"
   ```
3. תמשוך את הקובץ עם `scp` ותשלח אותו למשתמש עם `SendUserFile`. הוא סורק מהמסך. הריבוע מתחלף כל ~20 שניות, אז אם פספס — תייצר חדש, זה לוקח שניות.
4. **אם למשתמש אין מסך שני** (הוא על הטלפון בלבד), תשתמש בקוד בן 8 תווים במקום:
   `POST /api/default/auth/request-code` עם `{"phoneNumber":"<המספר>"}` מחזיר למשל `{"code":"577F-MFWT"}`. בטלפון: קישור מכשיר ← **"קישור באמצעות מספר טלפון במקום זאת"** ← להזין את המספר ← להקליד את הקוד. ⚠️ זה איטי יותר מסריקה ולעיתים קרובות לא מספיקים בזמן.
5. תאמת: המצב הוא `WORKING` והשדה `me` מכיל את המספר.

## שלב 8: בדיקה סופית
- תריץ את הסקיל `server-health`.
- המשתמש נכנס ל-`https://elichay.duckdns.org`, ומקבל קוד ב"הודעה לעצמי".
- תעדכן ב-`CLAUDE.md` את "מצב ההתקנה" ואת טבלת השלבים: שלב 1 מותקן.
