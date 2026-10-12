#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
force=()
[[ $# == 0 || ($# == 1 && $1 == --force) ]] || { echo 'Usage: rollback.sh [--force]' >&2; exit 2; }
if [[ ${1:-} == --force ]]; then force=(--force); fi
[[ $EUID == 0 ]] || { echo 'Run as root using infra/with-env.py' >&2; exit 1; }
# shellcheck source=infra/releases.sh
source "$root/infra/releases.sh"
exec 9>/var/lib/brodie/deploy.lock
flock -n 9 || { echo 'Another deployment or rollback is running' >&2; exit 1; }
previous=$(cat /var/lib/brodie/previous-sha)
validate_release "$previous"
current=$(basename "$(readlink -f "$release_base/current")")
validate_release "$current"
python3 "$root/infra/backup_env.py"
python3 "$root/infra/deploy_hold.py" "${force[@]}"
activate_release "$previous" "$current"
echo "Rolled back application to $previous; database migrations were retained"
