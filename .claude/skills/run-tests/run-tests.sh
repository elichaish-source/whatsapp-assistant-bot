#!/bin/bash
# מריץ את בדיקות ה-backend במכולה חד-פעמית, מול בסיס נתונים נפרד.
# לא נוגע בשירותים שרצים ולא בבסיס הנתונים של המערכת.
# שימוש: bash run-tests.sh [שם ענף]   (ברירת מחדל: main)
set -u
REPO=/root/whatsapp-assistant-bot
BRANCH=${1:-main}
SRC=/root/test-run
DB=assistant_test

PASS=$(grep ^POSTGRES_PASSWORD= $REPO/.env | cut -d= -f2)
NET=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' whatsapp-assistant-bot-db-1)
echo "BRANCH=$BRANCH  NETWORK=$NET"

rm -rf $SRC
git clone -q --branch "$BRANCH" --depth 1 https://github.com/elichaish-source/whatsapp-assistant-bot.git $SRC || exit 1
echo "CLONED $(cd $SRC && git log --oneline -1)"

docker exec -i whatsapp-assistant-bot-db-1 psql -U assistant -d assistant -c "DROP DATABASE IF EXISTS $DB" > /dev/null
docker exec -i whatsapp-assistant-bot-db-1 psql -U assistant -d assistant -c "CREATE DATABASE $DB" > /dev/null
echo "TEST DB READY"

docker run --rm --network "$NET" -v $SRC/backend:/app -w /app \
  -e TEST_DATABASE_URL="postgresql+psycopg://assistant:$PASS@db:5432/$DB" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  python:3.12-slim \
  bash -c 'set -o pipefail; pip install -q -r requirements.txt -r requirements-dev.txt && python -m pytest -q 2>&1 | tail -40'
CODE=$?

# ניקוי: הבסיס הזמני והקוד שהורד
docker exec -i whatsapp-assistant-bot-db-1 psql -U assistant -d assistant -c "DROP DATABASE IF EXISTS $DB" > /dev/null
rm -rf $SRC
echo "CLEANED"
echo "EXIT=$CODE"
exit $CODE
