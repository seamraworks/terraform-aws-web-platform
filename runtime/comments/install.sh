#!/bin/bash
# Dedicated Ubuntu host only. Pass the non-secret deployment descriptor.
set -euo pipefail
test "$(id -u)" = 0
descriptor="${1:-/etc/web-comments/deployment.json}"
python3 render-runtime.py --deployment "$descriptor" --environment-only
config_dir="$(python3 -c 'from deployment import load_deployment; import sys; print(load_deployment(sys.argv[1])["config_dir"])' "$descriptor")"
set -a
. "$config_dir/deployment.env"
set +a
cd "$COMMENTS_ROOT"
chmod 600 "$AWS_SHARED_CREDENTIALS_FILE"
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
install -d -o 1001 -g 1001 -m 750 data/remark data/state data/ops data/caddy data/proxy
.venv/bin/python host-config.py
python3 render-runtime.py
bash host-storage.sh
python3 storage-guard.py
python3 refresh-proxies.py
systemctl enable nftables
install -m 644 systemd/*.service systemd/*.timer /etc/systemd/system/
install -m 755 comments /usr/local/bin/comments
systemctl daemon-reload
docker compose build worker
docker compose config --quiet
systemctl enable --now "$COMMENTS_SERVICE_NAME-storage.timer" "$COMMENTS_SERVICE_NAME-cleanup.timer"
systemctl enable --now "$COMMENTS_SERVICE_NAME.service" "$COMMENTS_SERVICE_NAME-proxies.timer"
docker compose up -d --force-recreate
echo 'Started in the configured moderation mode.'
