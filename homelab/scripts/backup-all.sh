#!/usr/bin/env bash
# Serial backups bound peak I/O; fail the timer if any site's backup fails.
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
result=0
bash "$root/scripts/backup.sh" || result=1
if [[ -d $root/sites ]]; then
  for metadata in "$root"/sites/*/site.json; do
    [[ -f $metadata ]] || continue
    name=$(basename "$(dirname "$metadata")")
    bash "$root/scripts/backup-site.sh" "$name" || result=1
  done
fi
exit "$result"
