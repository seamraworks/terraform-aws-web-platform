#!/usr/bin/env python3
"""Host-side disk/inode guard; independent of Docker and the moderation worker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

GIB = 1024 ** 3
OPS = Path(os.environ.get("COMMENTS_ROOT", "/opt/web-comments")) / "data/ops"


def evaluate(total, free, files, available_files, paused=False):
    used = 1 - free / total
    inodes = 1 - available_files / files if files else 0
    critical = used >= .90 or free < GIB or inodes >= .90
    # Leave headroom before reopening, so the service does not flap at the limit.
    if paused and (used >= .85 or free < 2 * GIB or inodes >= .85):
        critical = True
    level = 'critical' if critical else 'warning' if used >= .80 or free < 2 * GIB or inodes >= .80 else 'ok'
    return {'level': level, 'used_percent': round(100 * used, 1),
            'free_bytes': free, 'inode_used_percent': round(100 * inodes, 1)}


def publish(ops, report):
    flag = ops / 'disk-pressure'
    if report['level'] == 'critical':
        atomic_write(flag, 'Storage capacity is low. The host guard will clear this after recovery.\n')
    else:
        flag.unlink(missing_ok=True)
    destination = ops / 'disk-health.json'
    try: previous = json.loads(destination.read_text()).get('level')
    except (OSError, ValueError): previous = None
    atomic_write(destination, json.dumps({**report, 'checked_at': time.time()}))
    if previous != report['level']:
        print('Comment storage: ' + json.dumps(report), flush=True)


def atomic_write(destination, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=destination.parent, prefix='.disk-', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        temporary.chmod(0o644)
        temporary.replace(destination)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def main():
    # All application data, Docker and host logs use the provisioned root disk.
    # Do not silently monitor the wrong filesystem if that layout changes.
    if any(path.stat().st_dev != Path('/').stat().st_dev
           for path in (OPS, *(OPS.parent / name for name in ('remark', 'state', 'caddy', 'proxy')),
                        Path('/var/log'), Path('/var/lib/docker'))):
        raise RuntimeError('Storage layout changed; configure monitoring for every filesystem')
    usage, nodes = shutil.disk_usage(OPS), os.statvfs(OPS)
    report = evaluate(usage.total, usage.free, nodes.f_files, nodes.f_favail,
                      (OPS / 'disk-pressure').exists())
    # Protect traffic before any rotation work. A failed rotation must also
    # make the CloudWatch heartbeat unhealthy, even while capacity is sufficient.
    if report['level'] == 'critical':
        atomic_write(OPS / 'disk-pressure', 'Storage capacity is low.\n')
    try:
        result = subprocess.run(['/usr/sbin/logrotate', '--state', '/var/lib/logrotate/' + os.environ.get('COMMENTS_SERVICE_NAME', 'web-comments') + '.status',
                                 '/etc/logrotate-' + os.environ.get('COMMENTS_SERVICE_NAME', 'web-comments') + '.conf'], timeout=40, check=False)
        report['rotation_ok'] = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        report['rotation_ok'] = False
    if not report['rotation_ok']:
        if report['level'] == 'ok': report['level'] = 'warning'
        report['reason'] = 'Host log rotation failed'
    publish(OPS, report)


if __name__ == '__main__': main()
