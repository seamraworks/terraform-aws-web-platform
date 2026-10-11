"""Validate non-secret deployment identity before reading or rendering secrets."""
import json
import os
from pathlib import Path
import re
import shlex
import urllib.parse


def load_deployment(path=None):
    value = json.loads(Path(path or os.environ.get("COMMENTS_DEPLOYMENT", "/etc/web-comments/deployment.json")).read_text())
    if "value" in value: value = value["value"]
    defaults = {"runtime_dir": "/opt/web-comments", "config_dir": "/etc/web-comments",
                "service_name": "web-comments", "nft_table": "web_comments",
                "origin_header": "X-Comments-Origin", "brand_name": "Website", "timezone": "UTC"}
    value = {**defaults, **value}
    for name in ("runtime_dir", "config_dir"):
        if not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+", value[name]):
            raise ValueError("Use an absolute deployment directory without spaces or traversal")
    for name in ("service_name", "site_id", "nft_table"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value[name]): raise ValueError("Invalid deployment identifier")
    if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d+", value["region"]): raise ValueError("Invalid AWS region")
    url = urllib.parse.urlsplit(value["public_url"])
    if url.scheme != "https" or url.path not in {"", "/"} or url.query or url.fragment or url.username:
        raise ValueError("Expected the HTTPS comments origin")
    value["public_domain"] = url.netloc
    for name in ("public_domain", "origin_hostname"):
        if not re.fullmatch(r"[a-z0-9.-]+", value[name]): raise ValueError("Invalid deployment domain")
    if not re.fullmatch(r"[A-Za-z0-9-]+", value["origin_header"]): raise ValueError("Invalid origin header")
    if not re.fullmatch(r"/[A-Za-z0-9/_-]+", value["config_parameter"]): raise ValueError("Invalid SSM parameter path")
    return value


def runtime_environment(deployment):
    values = {"COMMENTS_ROOT": deployment["runtime_dir"], "COMMENTS_CONFIG_DIR": deployment["config_dir"],
              "COMMENTS_SERVICE_NAME": deployment["service_name"], "COMMENTS_NFT_TABLE": deployment["nft_table"],
              "COMMENTS_DEPLOYMENT": deployment["config_dir"] + "/deployment.json",
              "AWS_SHARED_CREDENTIALS_FILE": deployment["config_dir"] + "/credentials"}
    return "".join(key + "=" + shlex.quote(value) + "\n" for key, value in values.items())


def validate_config(config, deployment):
    if config.get("site") != deployment["site_id"] or config.get("region") != deployment["region"]:
        raise ValueError("Runtime configuration belongs to a different deployment")
    required = ["origin_secret", "remark_secret", "admin_password", "webhook_secret", "backup_bucket"]
    if config.get("moderation_provider", "none") == "openai":
        required += ["openai_api_key", "model", "monthly_budget_usd", "input_usd_per_million", "output_usd_per_million"]
    if config.get("google_client_id"): required += ["google_client_secret"]
    if config.get("github_client_id"): required += ["github_client_secret"]
    if any(config.get(key) is None or config.get(key) == "" or str(config[key]).startswith("REPLACE_") for key in required):
        raise ValueError("Provision the enabled providers and required runtime settings")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", config["origin_secret"]): raise ValueError("Invalid origin secret")
    if config.get("mode", "report") not in {"report", "auto"}: raise ValueError("Invalid moderation mode")
    if config.get("mode") == "auto" and not config.get("admin_ids"):
        raise ValueError("Register an owner before automatic removal")
    if not config.get("article_hosts") or not config.get("article_path_prefix", "").startswith("/"):
        raise ValueError("Configure permitted article hosts and path prefix")
    if config["backup_bucket"] != deployment["backup_bucket"]:
        raise ValueError("Backup destination does not match the deployment")
    return config
