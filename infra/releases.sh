#!/usr/bin/env bash
# Shared by deploy and rollback, which hold deploy.lock throughout.
release_base=/opt/brodie
release_services=(brodie-worker chert-agent brodie-dispatcher brodie-heartbeat-check brodie-reconciler.timer brodie-backup.timer)

validate_release() {
  [[ $1 =~ ^[0-9a-f]{40}$ && -f $release_base/releases/$1/.release-ready && -x $release_base/releases/$1/.venv/bin/python ]] || {
    echo 'Release is missing or incomplete' >&2
    return 1
  }
}

activate_release() {
  local sha=$1 old=$2
  systemctl stop brodie-reconciler.timer brodie-backup.timer brodie-heartbeat-check brodie-worker chert-agent brodie-dispatcher brodie-reconciler.service brodie-backup.service
  if [[ -n $old && $old != "$sha" ]]; then
    printf '%s\n' "$old" >/var/lib/brodie/previous-sha.new
    mv /var/lib/brodie/previous-sha.new /var/lib/brodie/previous-sha
  fi
  # Rename on the same filesystem makes the visible switch atomic.
  ln -sfn "$release_base/releases/$sha" "$release_base/current.new"
  mv -Tf "$release_base/current.new" "$release_base/current"
  install -m 0644 "$release_base/current/infra/systemd/"* /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now "${release_services[@]}"
  bash "$release_base/current/infra/health.sh"
  printf '%s\n' "$sha" >/var/lib/brodie/deployed-sha
}
