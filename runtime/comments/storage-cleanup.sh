#!/bin/bash
# This VM is dedicated to comments. Keep data and all images used by containers.
set -euo pipefail
apt-get clean
docker image prune --all --force --filter until=168h
docker builder prune --all --force --filter until=168h --keep-storage 256MB
