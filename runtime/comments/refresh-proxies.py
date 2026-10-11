#!/usr/bin/env python3
"""Atomically update the host firewall and Caddy's trusted CloudFront peers."""
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import urllib.request


def main():
    with urllib.request.urlopen("https://ip-ranges.amazonaws.com/ip-ranges.json", timeout=30) as response:
        values = json.load(response)
    ranges = sorted({str(ipaddress.ip_network(item["ip_prefix"])) for item in values["prefixes"]
                     if item["service"] == "CLOUDFRONT_ORIGIN_FACING"})
    if not 10 <= len(ranges) <= 500: raise ValueError("Unexpected AWS range list; keeping last known configuration")
    root = Path(os.environ.get("COMMENTS_ROOT", "/opt/web-comments")) / "data/proxy"
    root.mkdir(parents=True, exist_ok=True)
    existing = subprocess.run(["nft", "list", "table", "inet", os.environ.get("COMMENTS_NFT_TABLE", "web_comments")], capture_output=True).returncode == 0
    rules = ("delete table inet " + os.environ.get("COMMENTS_NFT_TABLE", "web_comments") + "\n" if existing else "") + """table inet web_comments {
      set cloudfront4 { type ipv4_addr; flags interval; elements = { RANGES } }
      chain input {
        type filter hook input priority -10; policy accept;
        iifname "lo" accept
        tcp dport 443 ip saddr @cloudfront4 accept
        tcp dport 443 drop
      }
    }
    """.replace("web_comments", os.environ.get("COMMENTS_NFT_TABLE", "web_comments")).replace("RANGES", ", ".join(ranges))
    subprocess.run(["nft", "-c", "-f", "-"], input=rules, text=True, check=True)
    subprocess.run(["nft", "-f", "-"], input=rules, text=True, check=True)
    temporary = root / "trusted.caddy.next"
    temporary.write_text("trusted_proxies static " + " ".join(ranges) + "\n")
    temporary.replace(root / "trusted.caddy")
    # Keep this table across reboot even if AWS's range feed is temporarily down.
    persisted = subprocess.check_output(["nft", "list", "table", "inet", os.environ.get("COMMENTS_NFT_TABLE", "web_comments")], text=True)
    Path("/etc/nftables.conf").write_text("#!/usr/sbin/nft -f\n" + persisted)
    running = subprocess.run(["docker", "compose", "ps", "--status", "running", "--services"],
                             cwd=os.environ.get("COMMENTS_ROOT", "/opt/web-comments"), capture_output=True, text=True, check=True)
    if "caddy" in running.stdout.splitlines():
        subprocess.run(["docker", "compose", "exec", "-T", "caddy", "caddy", "reload",
                        "--config", "/etc/caddy/Caddyfile"], cwd=os.environ.get("COMMENTS_ROOT", "/opt/web-comments"), check=True)


if __name__ == "__main__": main()
