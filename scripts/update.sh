#!/usr/bin/env bash
# עדכון לגרסה האחרונה מ-GitHub: מוריד את הקוד, מגבה ומפעיל מחדש.
set -euo pipefail

cd "$(dirname "$0")/.."
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

git pull --ff-only
$SUDO scripts/backup.sh
$SUDO docker compose up -d --build
echo "העדכון הושלם."
