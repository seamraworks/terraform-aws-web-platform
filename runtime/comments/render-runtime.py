#!/usr/bin/env python3
"""Render a deployment's host files from public templates; no cloud mutations."""
import argparse
from html import escape
import json
import os
from pathlib import Path
import re
import urllib.parse
from deployment import load_deployment, runtime_environment, validate_config

ROOT = Path(__file__).resolve().parent


def render_files(config, deployment, target):
    validate_config(config, deployment)
    brand = config.get("brand_name", deployment["brand_name"])
    email = config.get("email_from", "")
    owner = config.get("acme_email", config.get("digest_to", ""))
    for address in (email, owner):
        if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", address): raise ValueError("Configure sender and certificate contact")
    for host in config.get("embed_hosts", config["article_hosts"]):
        if not re.fullmatch(r"[a-z0-9.-]+", host): raise ValueError("Invalid article host")
    website, privacy, logo = config["website_url"], config["privacy_url"], config.get("logo_url", "")
    for url in (website, privacy, *([logo] if logo else [])):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or re.search(r'[\s"<>]', url):
            raise ValueError("Configure HTTPS branding URLs")
    if any("\n" in str(v) or "\r" in str(v) for v in (brand, email, owner)):
        raise ValueError("Branding fields must be single-line")
    values = {"RUNTIME_DIR": deployment["runtime_dir"], "CONFIG_DIR": deployment["config_dir"],
              "SERVICE_NAME": deployment["service_name"], "SITE": config["site"], "OWNER_EMAIL": owner,
              "PUBLIC_URL": deployment["public_url"], "PUBLIC_DOMAIN": deployment["public_domain"],
              "ORIGIN_DOMAIN": deployment["origin_hostname"], "ORIGIN_HEADER": deployment["origin_header"],
              "ALLOWED_HOSTS": ",".join(config.get("embed_hosts", config["article_hosts"])), "PRIVACY_URL": privacy,
              "EMAIL_FROM": email, "BRAND_NAME": brand, "SMTP_HOST": "email-smtp." + config["region"] + ".amazonaws.com"}
    target = Path(target)
    for template in (ROOT / "templates/runtime").rglob("*.tmpl"):
        relative = template.relative_to(ROOT / "templates/runtime")
        destination = target / str(relative).removesuffix(".tmpl").replace("web-comments", deployment["service_name"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = template.read_text()
        for key, value in values.items(): text = text.replace("@@" + key + "@@", value)
        if re.search(r"@@[A-Z_]+@@", text): raise ValueError("Unresolved template field")
        if relative.name.startswith("compose"):
            text = re.sub(r"AUTH_EMAIL_FROM:.*", lambda _: "AUTH_EMAIL_FROM: " + json.dumps(f'\"{brand} comments\" <{email}>'), text)
            text = re.sub(r"AUTH_EMAIL_SUBJ:.*", lambda _: "AUTH_EMAIL_SUBJ: " + json.dumps("Your " + brand + " comment sign-in code"), text)
        destination.write_text(text, newline="\n")
        if destination.suffix == ".sh" or destination.name == "comments": destination.chmod(0o755)
    login = (ROOT / "templates/email_confirmation_login.html.tmpl").read_text()
    logo_html = (f'<img src="{escape(logo, quote=True)}" width="360" alt="{escape(brand, quote=True)}" '
                 'style="display:block;width:100%;max-width:360px;height:auto;border:0">' if logo
                 else f'<strong style="font-size:24px">{escape(brand)}</strong>')
    for key, value in {"BRAND_NAME": escape(brand), "WEBSITE_URL": escape(website, quote=True), "LOGO_HTML": logo_html}.items():
        login = login.replace("@@" + key + "@@", value)
    destination = target / "templates/email_confirmation_login.html.tmpl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(login, newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment")
    parser.add_argument("--environment-only", action="store_true")
    args = parser.parse_args()
    deployment = load_deployment(args.deployment)
    directory = Path(deployment["config_dir"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    (directory / "deployment.env").write_text(runtime_environment(deployment), newline="\n")
    if not args.environment_only:
        config = json.loads((directory / "config.json").read_text())
        render_files(config, deployment, deployment["runtime_dir"])


if __name__ == "__main__": main()
