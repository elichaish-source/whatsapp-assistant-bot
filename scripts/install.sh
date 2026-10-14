#!/usr/bin/env bash
# התקנה מלאה של המערכת על שרת Ubuntu חדש (Oracle או Hetzner).
# מריצים מתוך תיקיית הפרויקט: ./scripts/install.sh
# אפשר להריץ שוב בבטחה: שלבים שכבר בוצעו מדולגים.
set -euo pipefail

WAHA_VERSION="2026.9.2"
BACKUP_HOUR="3"

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
ok() { printf '\033[1;32m✔ %s\033[0m\n' "$1"; }
fail() { printf '\033[1;31m✘ %s\033[0m\n' "$1" >&2; exit 1; }

# --- 1. Docker ---
step "1/6 התקנת Docker"
if command -v docker >/dev/null 2>&1; then
  ok "Docker כבר מותקן"
else
  curl -fsSL https://get.docker.com | $SUDO sh
  [ -n "$SUDO" ] && $SUDO usermod -aG docker "$USER"
  ok "Docker הותקן"
fi
DOCKER="$SUDO docker"

# --- 2. פתיחת פורטים 80 ו-443 על השרת ---
step "2/6 פתיחת פורטים 80 ו-443"
if command -v ufw >/dev/null 2>&1 && $SUDO ufw status | grep -q "Status: active"; then
  $SUDO ufw allow 80/tcp >/dev/null
  $SUDO ufw allow 443/tcp >/dev/null
  ok "נפתחו ב-ufw"
fi
# בשרתי Oracle יש חוקי iptables שחוסמים הכול חוץ מ-SSH
if $SUDO iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then
  for port in 80 443; do
    if ! $SUDO iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
      $SUDO iptables -I INPUT 1 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
    fi
  done
  if command -v netfilter-persistent >/dev/null 2>&1; then
    $SUDO netfilter-persistent save >/dev/null 2>&1
  fi
  ok "נפתחו ב-iptables"
else
  ok "אין חסימה על השרת"
fi

# --- 3. קובץ הגדרות ---
step "3/6 קובץ הגדרות (.env)"
if [ -f .env ]; then
  ok "קובץ .env כבר קיים, משאיר אותו כמו שהוא"
else
  echo "מספר הוואטסאפ שלך (למשל 0501234567):"
  read -r phone
  phone="$(echo "$phone" | tr -cd '0-9')"
  [[ "$phone" == 0* ]] && phone="972${phone:1}"
  [[ "$phone" =~ ^972[0-9]{8,9}$ ]] || fail "המספר לא תקין: $phone"

  echo "שם התת-דומיין ב-DuckDNS (Enter עבור elichay):"
  read -r subdomain
  subdomain="${subdomain:-elichay}"

  echo "ה-token של DuckDNS (לא יוצג על המסך בזמן ההדבקה):"
  read -rs duckdns_token
  echo
  [ -n "$duckdns_token" ] || fail "לא הוזן token"

  case "$(uname -m)" in
    aarch64 | arm64) waha_tag="arm-$WAHA_VERSION" ;;
    *) waha_tag="latest-$WAHA_VERSION" ;;
  esac

  umask 077
  cat > .env <<EOF
DOMAIN=$subdomain.duckdns.org
DUCKDNS_SUBDOMAIN=$subdomain
DUCKDNS_TOKEN=$duckdns_token
OWNER_PHONE=$phone
WAHA_IMAGE_TAG=$waha_tag
POSTGRES_PASSWORD=$(openssl rand -hex 24)
WAHA_API_KEY=$(openssl rand -hex 24)
WAHA_DASHBOARD_PASSWORD=$(openssl rand -hex 12)
EOF
  ok "נוצר .env עם סיסמאות אקראיות (גרסת WAHA: $waha_tag)"
fi
DOMAIN="$(grep '^DOMAIN=' .env | cut -d= -f2)"

# --- 4. הפעלת המערכת ---
step "4/6 הפעלת המערכת (בפעם הראשונה זה לוקח כמה דקות)"
$DOCKER compose up -d --build

echo "ממתין שהשרת יעלה..."
for _ in $(seq 1 60); do
  if $DOCKER compose exec -T backend python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" >/dev/null 2>&1; then
    ok "השרת פועל"
    break
  fi
  sleep 3
done || true
$DOCKER compose exec -T backend python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" >/dev/null 2>&1 \
  || fail "השרת לא עלה. הרץ: sudo docker compose logs backend"

# --- 5. גיבוי יומי ---
step "5/6 גיבוי יומי של בסיס הנתונים"
chmod +x scripts/*.sh
# כדי שהגיבוי ירוץ לפי שעון ישראל
$SUDO timedatectl set-timezone Asia/Jerusalem 2>/dev/null || true
echo "15 $BACKUP_HOUR * * * root $PROJECT_DIR/scripts/backup.sh >> /var/log/assistant-backup.log 2>&1" \
  | $SUDO tee /etc/cron.d/assistant-backup >/dev/null
$SUDO scripts/backup.sh
ok "גיבוי ראשון נשמר ב-$PROJECT_DIR/backups. גיבוי חדש כל יום ב-0$BACKUP_HOUR:15 (14 אחרונים נשמרים)"

# --- 6. סיכום ---
step "6/6 סיום"
ok "ההתקנה הושלמה"
cat <<EOF

נשאר רק לחבר את הוואטסאפ (פעם אחת):
  1. סגור את החיבור הזה (exit) והתחבר מחדש מהמחשב עם מנהרה:
       ssh -L 3000:localhost:3000 $(whoami)@<כתובת-השרת>
  2. פתח בדפדפן:  http://localhost:3000/dashboard
     משתמש: admin
     סיסמה: מופיעה בשורה WAHA_DASHBOARD_PASSWORD בפקודה:  grep WAHA_ .env
  3. בסשן default סרוק את ה-QR: וואטסאפ ← מכשירים מקושרים ← קישור מכשיר

אחר כך הדשבורד:  https://$DOMAIN
EOF
