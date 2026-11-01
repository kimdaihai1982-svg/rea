#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p backups
exec 9>backups/.lock
flock -n 9 || { echo 'Có backup/restore đang chạy'; exit 1; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work=$(mktemp -d "$PWD/backups/.work.XXXXXX")
paused=0
cleanup() {
  if [[ $paused == 1 ]]; then docker compose start web mqtt kuma files || true; fi
  rm -rf "$work"
}
trap cleanup EXIT
# Stop writers for a consistent application snapshot; DB stays running for dump.
paused=1
docker compose stop web mqtt kuma files
docker compose exec -T db sh -c 'exec mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --all-databases --single-transaction --routines --events --triggers' > "$work/database.sql"
# No Docker socket mounted into any UI or backup container.
for svc in mqtt kuma files; do
  docker compose run --rm --no-deps --user 0 --entrypoint tar "$svc" czf - -C "$(case $svc in mqtt) echo /mosquitto/data;; kuma) echo /app/data;; files) echo /database;; esac)" . > "$work/$svc.tgz"
done
tar czf "$work/config.tgz" .env compose.yaml config secrets projects php portal scripts dashboard packages.json README.md SECURITY.md MULTISITE.md DASHBOARD.md .env.example .gitignore
printf '%s\n' "$stamp" > "$work/COMPLETE"
(cd "$work"; sha256sum database.sql *.tgz COMPLETE > SHA256SUMS)
mv "$work" "backups/$stamp"
# Local retention: only complete timestamped snapshots, 14 days.
find backups -mindepth 1 -maxdepth 1 -type d -name '20??????T??????Z' -mtime +14 -exec rm -rf -- {} +
echo "Backup thành công: backups/$stamp (chứa mật khẩu, phải mã hóa khi chép ra ngoài)."
