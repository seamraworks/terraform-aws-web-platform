#!/usr/bin/env python3
"""Retrieve one deployment's SSM configuration; never print secrets."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import boto3
from deployment import load_deployment, validate_config


def smtp_password(secret, region):
    value = ("AWS4" + secret).encode()
    for text in ("11111111", region, "ses", "aws4_request", "SendRawEmail"):
        value = hmac.new(value, text.encode(), hashlib.sha256).digest()
    return base64.b64encode(b"\x04" + value).decode()


def write_secret(path, value, group_read=False):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        handle.write(value)
        temp = Path(handle.name)
    os.chmod(temp, 0o640 if group_read else 0o600)
    os.chown(temp, 0, 1001 if group_read else 0)
    temp.replace(path)


def main():
    if os.geteuid() != 0: raise SystemExit("Run as root")
    deployment = load_deployment()
    root = Path(deployment["config_dir"])
    session = boto3.Session(region_name=deployment["region"])
    credentials = session.get_credentials().get_frozen_credentials()
    result = session.client("ssm").get_parameter(Name=deployment["config_parameter"], WithDecryption=True)
    config = validate_config(json.loads(result["Parameter"]["Value"]), deployment)
    if credentials.token and config.get("email_login_enabled"):
        raise SystemExit("SES SMTP requires the restricted host user's long-lived key")
    config.update(aws_access_key_id=credentials.access_key, aws_secret_access_key=credentials.secret_key)
    if credentials.token: config["aws_session_token"] = credentials.token
    remark = {
        "SECRET": config["remark_secret"], "ADMIN_PASSWD": config["admin_password"],
        "AUTH_GOOGLE_CID": config.get("google_client_id", ""), "AUTH_GOOGLE_CSEC": config.get("google_client_secret", ""),
        "AUTH_GITHUB_CID": config.get("github_client_id", ""), "AUTH_GITHUB_CSEC": config.get("github_client_secret", ""),
        "AUTH_ANON": str(config.get("anonymous_enabled", True)).lower(),
        "AUTH_EMAIL_ENABLE": str(config.get("email_login_enabled", False)).lower(),
        "ADMIN_SHARED_ID": ",".join(config.get("admin_ids", [])),
        "SMTP_USERNAME": credentials.access_key,
        "SMTP_PASSWORD": smtp_password(credentials.secret_key, config["region"]) if not credentials.token else "",
        "NOTIFY_WEBHOOK_HEADERS": "Authorization:Bearer " + config["webhook_secret"],
    }
    if any("\n" in value or "\r" in value for value in remark.values()): raise SystemExit("Runtime values must be single-line")
    write_secret(root / "remark.env", "".join(k + "=" + v + "\n" for k, v in remark.items()))
    write_secret(root / "caddy.env", "ORIGIN_SECRET=" + config["origin_secret"] + "\n")
    write_secret(root / "config.json", json.dumps(config), group_read=True)
    print("Runtime configuration refreshed; secrets were not printed.")


if __name__ == "__main__": main()
