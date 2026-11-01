#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
[[ $# == 1 && $1 =~ ^[a-z][a-z0-9-]{0,31}$ ]] || { echo 'Dùng: backup-site.sh ten-site'; exit 1; }
cd "$root/sites/$1"
[[ -f compose.yaml && -f site.json ]] || exit 1
umask 077
mkdir -p backups
exec 9>backups/.lock
flock -n 9 || exit 1
work=$(mktemp -d "$PWD/backups/.work.XXXXXX")
paused=0
cleanup() {
  if [[ $paused == 1 ]]; then docker compose start web || true; fi
  rm -rf "$work"
}
trap cleanup EXIT
paused=1
docker compose stop web
docker compose exec -T db sh -c 'exec mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --all-databases --single-transaction --routines --events --triggers' > "$work/database.sql"
tar czf "$work/site.tgz" .env site.json compose.yaml config php projects
printf 'site snapshot v1\n' > "$work/COMPLETE"
(cd "$work"; sha256sum database.sql site.tgz COMPLETE > SHA256SUMS)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
[[ ! -e backups/$stamp ]] || { echo 'Snapshot cùng giây đã tồn tại'; exit 1; }
mv "$work" "backups/$stamp"
find backups -mindepth 1 -maxdepth 1 -type d -name '20??????T??????Z' -mtime +14 -exec rm -rf -- {} +
echo "Snapshot: $PWD/backups/$stamp"
