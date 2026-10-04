#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_FILE="${SALTTIGER_CONFIG_FILE:-/root/.config/salttiger/production.env}"
if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

# This job intentionally processes only links already present in SQLite. It does
# not crawl SaltTiger or bypass the site's robots.txt policy.
LIBRARY_DIR="${SALTTIGER_LIBRARY_DIR:-/mnt/d/OneDrive/OneDrive/30_Knowledge_笔记阅读学习/salttiger_book}"
ST_COMMAND="${SALTTIGER_ST_COMMAND:-/opt/salttiger/venv/bin/st}"
DOWNLOAD_LIMIT="${SALTTIGER_DOWNLOAD_LIMIT:-20}"
LOG_DIR="${SALTTIGER_LOG_DIR:-/var/log/salttiger}"
LOCK_FILE="${SALTTIGER_LOCK_FILE:-/run/lock/salttiger-pan.lock}"

mkdir -p "$LOG_DIR" "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another SaltTiger Pan job is already running." >&2
  exit 75
fi

run_id="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="$LOG_DIR/pan-$run_id.log"
exec > >(tee -a "$log_file") 2>&1

status_json() {
  python3 - "$LIBRARY_DIR/.salttiger/library.sqlite3" <<'PY'
import json
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
statuses = dict(
    connection.execute(
        "select status, count(*) from downloads where provider = 'baidu_pan' group by status"
    )
)
print(json.dumps({"downloads": statuses}, ensure_ascii=False, separators=(",", ":")))
PY
}

finish() {
  exit_code=$?
  trap - EXIT
  summary="$(status_json 2>/dev/null || printf '{"downloads":{}}')"
  echo "run_id=$run_id exit_code=$exit_code summary=$summary"

  if [[ -n "${SALTTIGER_NOTIFY_URL:-}" ]]; then
    SALTTIGER_EXIT_CODE="$exit_code" SALTTIGER_SUMMARY="$summary" python3 <<'PY' || true
import json
import os
import urllib.request

exit_code = int(os.environ["SALTTIGER_EXIT_CODE"])
summary = json.loads(os.environ["SALTTIGER_SUMMARY"])
payload = json.dumps(
    {
        "title": "SaltTiger download job",
        "message": f"exit={exit_code} status={summary.get('downloads', {})}",
        "tags": ["white_check_mark" if exit_code == 0 else "warning"],
    }
).encode("utf-8")
request = urllib.request.Request(
    os.environ["SALTTIGER_NOTIFY_URL"],
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=20) as response:
    response.read()
PY
  fi
  exit "$exit_code"
}
trap finish EXIT

echo "run_id=$run_id started=$(date -Is) library=$LIBRARY_DIR limit=$DOWNLOAD_LIMIT"
test -d "$LIBRARY_DIR"
test -x "$ST_COMMAND"
"$ST_COMMAND" bdpan-doctor
"$ST_COMMAND" download-pan \
  --library "$LIBRARY_DIR" \
  --limit "$DOWNLOAD_LIMIT" \
  --retry-failed \
  --confirm
