#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
[[ $# == 2 && $2 == --confirm-overwrite ]] || { echo "Dùng: $0 /duong/dan/snapshot --confirm-overwrite"; exit 1; }
snapshot=$(realpath "$1")
[[ -f "$snapshot/COMPLETE" ]] || { echo 'Snapshot không hoàn chỉnh'; exit 1; }
(cd "$snapshot"; sha256sum -c SHA256SUMS)
mkdir -p backups
exec 9>backups/.lock
flock -n 9 || exit 1
# Preserve current configuration before replacing anything.
umask 077
tar czf "backups/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).tgz" --ignore-failed-read .env config secrets projects compose.yaml
docker compose down
# Only restore snapshots you created and trust (tar can overwrite files).
tar xzf "$snapshot/config.tgz"
docker compose up -d db
for i in {1..60}; do
  if docker compose exec -T db healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; then break; fi
  sleep 2
done
docker compose exec -T db healthcheck.sh --connect --innodb_initialized
# Restores to the current DB volume: root password must match snapshot.
docker compose exec -T db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD"' < "$snapshot/database.sql"
for svc in mqtt files; do
  dest=$(case $svc in mqtt) echo /mosquitto/data;; files) echo /database;; esac)
  docker compose run --rm --no-deps --user 0 --entrypoint sh "$svc" -c 'find "$1" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar xzf - -C "$1"' sh "$dest" < "$snapshot/$svc.tgz"
done
docker compose up -d --build
echo 'Restore hoàn tất; kiểm tra log, PHP, SQL, MQTT và giám sát trước khi mở traffic.'
