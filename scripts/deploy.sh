#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
force=()
for arg in "$@"; do
  case "$arg" in
    --dry-run)
      printf '%s\n' 'Deploy plan: fetch; export releases/<sha>; build isolated venv; check and migrate; hold for idle calls; atomically switch current; restart; health check; keep 5 releases'
      exit 0 ;;
    --force) force=(--force) ;;
    *) echo 'Usage: deploy.sh [--dry-run] [--force]' >&2; exit 2 ;;
  esac
done
[[ $EUID == 0 && ($root == /opt/brodie || $root == /opt/brodie/current || $root == /opt/brodie/releases/*) ]] || {
  echo 'Run as root from /opt/brodie using infra/with-env.py' >&2; exit 1;
}
: "${SUPABASE_DB_URL:?required}"
# shellcheck source=infra/releases.sh
source "$root/infra/releases.sh"
install -d -m 0700 /var/lib/brodie
exec 9>/var/lib/brodie/deploy.lock
flock -n 9 || { echo 'Another deployment or rollback is running' >&2; exit 1; }
git_as_user() { runuser -u brodie -- git -C "$release_base" "$@"; }
[[ -z $(git_as_user status --porcelain --untracked-files=no) ]] || { echo 'Tracked checkout changes; refusing deploy' >&2; exit 1; }
branch=$(git_as_user symbolic-ref --short -q HEAD || cat /var/lib/brodie/deploy-branch)
printf '%s\n' "$branch" >/var/lib/brodie/deploy-branch
git_as_user fetch origin "$branch"
sha=$(git_as_user rev-parse FETCH_HEAD)
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release SHA' >&2; exit 1; }
previous=''
if [[ -L $release_base/current ]]; then
  previous=$(basename "$(readlink -f "$release_base/current")")
  validate_release "$previous"
fi
release="$release_base/releases/$sha"
install -d -m 0755 "$release_base/releases"
install -d -m 0755 -o brodie -g brodie "$release_base/data"
if [[ ! -f $release/.release-ready ]]; then
  [[ ! -e $release ]] || { echo 'Incomplete release exists; inspect and remove it before retrying' >&2; exit 1; }
  install -d -m 0755 -o brodie -g brodie "$release"
  trap 'rm -rf -- "$release"' EXIT
  git_as_user archive "$sha" | runuser -u brodie -- tar -x -C "$release"
  [[ ! -e $release/data && ! -L $release/data ]] || { echo 'Release data must remain outside git' >&2; exit 1; }
  ln -s "$release_base/data" "$release/data"
  runuser -u brodie -- uv venv --python 3.12 "$release/.venv"
  runuser -u brodie -- uv pip sync --python "$release/.venv/bin/python" "$release/requirements.txt"
  runuser -u brodie -- uv pip check --python "$release/.venv/bin/python"
  touch "$release/.release-ready"
  trap - EXIT
fi
validate_release "$sha"
python3 "$root/infra/backup_env.py"
(cd "$release" && python3 infra/migrations.py)
python3 "$root/infra/deploy_hold.py" "${force[@]}"
activate_release "$sha" "$previous"
python3 "$root/infra/prune_releases.py"
echo "Deployed $sha (previous ${previous:-none})"
