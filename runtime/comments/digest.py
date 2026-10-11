"""Human-readable owner email; comment text is always treated as plain text."""
import datetime as dt
from html import escape
from html.parser import HTMLParser
import json
import re
import urllib.parse


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, data): self.parts.append(data)
    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "pre"}: self.parts.append("\n")
    def handle_starttag(self, tag, attrs):
        if tag == "br": self.parts.append("\n")


def original_text(comment):
    if comment.get("orig"): return comment["orig"][:8000]
    parser = PlainText(); parser.feed(comment.get("text", "")[:32000])
    return "".join(parser.parts).strip()[:8000]


def discussion_link(row, config=None):
    config = config or {}
    url = urllib.parse.urlsplit(row["url"])
    if (url.scheme != "https" or url.netloc not in config.get("article_hosts", [])
            or not url.path.startswith(config.get("article_path_prefix", "/")) or url.query or url.fragment
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", row["id"])):
        return None
    # A first-party discussion page also works before the Journal is published.
    return config["public_url"].rstrip("/") + "/web/iframe.html?" + urllib.parse.urlencode({
        "host": config["public_url"], "site_id": config["site"],
        "url": row["url"], "theme": "light",
    }) + "#remark42__comment-" + row["id"]


def build_digest(now, mode, changes, jobs, comments, archived, service_health=None, config=None):
    config = config or {}
    brand = config.get("brand_name", "Website")
    jobs = {row["id"]: dict(row) for row in jobs}
    reviews = [r for r in jobs.values() if r["state"] in {"review", "report_spam", "failed"}
               or (r["state"] == "pending" and r["attempts"] > 0)]
    removed_ids = {r["id"] for r in changes if r["action"] == "removed"
                   and r["id"] in jobs and jobs[r["id"]]["state"] == "removed"}
    restored_ids = {r["id"] for r in changes if r["action"] == "restored"
                    and r["id"] in jobs and jobs[r["id"]]["state"] == "keep"}
    changed_reviews = any(r["id"] in {j["id"] for j in reviews} for r in changes)
    service = [r for r in changes if r["id"] is None and r["action"] in {"failure", "storage"}]
    notes = []
    for r in service:
        if r["action"] == "failure":
            task = r["detail"].split(":", 1)[0]
            if (service_health or {}).get(task) is True: continue
            name = {"scan": "comment sweep", "backup": "backup", "history_cleanup": "audit cleanup"}.get(task, "background")
            notes.append(f"The {name} task reported a problem. Check service health if it continues.")
    service_failure = bool(notes)
    storage = [r for r in service if r["action"] == "storage"]
    storage_problem = False
    if storage:
        try:
            report = json.loads(storage[-1]["detail"])
            storage_problem = report["level"] != "ok"
            notes.append("Storage needs attention; check the operational alert." if storage_problem
                         else "Storage is healthy again; no action needed.")
        except (ValueError, KeyError, TypeError):
            storage_problem = True; notes.append("Storage monitoring needs attention.")
    if not (changed_reviews or removed_ids or service_failure or storage_problem):
        return None  # Do not email resolved retries, maintenance or routine backups alone.

    removed = [row for row in jobs.values() if row['id'] in removed_ids]
    summary = f"{len(reviews)} needing attention · {len(removed)} removed"
    date = now.strftime("%d %B %Y")
    subject = f"{brand} comments: {summary}"
    intro = (f"Scheduled daily summary for {date}, {config.get("digest_hour", 9):02d}:00 {config.get("timezone", "UTC")}. "
             "Activity since the previous summary; a new comment is not required to trigger this email.")
    mode_text = "Automatic spam removal is on." if mode == "auto" else "Report mode: automatic removal is off."
    plain = ["Example Website — Journal comments", summary, "", intro, mode_text, ""]
    sections = []

    def cards(rows, heading, deleted=False, limit=20):
        if not rows: return
        plain.extend([heading, "=" * len(heading), ""])
        items = []
        for row in rows[:limit]:
            comment = archived.get(row["id"]) if deleted else comments.get(row["id"])
            comment = comment or {}
            author = comment.get("user", {}).get("name", "Unknown author")[:100]
            title = comment.get("title", "")
            if not title or title.lower() in {"comments", "remark42"}:
                title = urllib.parse.unquote(urllib.parse.urlsplit(row["url"]).path.rsplit("/", 1)[-1])
                title = title.removesuffix(".html").replace("-", " ").capitalize()
            title = title[:300]
            text = original_text(comment) or "Original text could not be loaded; check the discussion or archive."
            link = discussion_link(row, config)
            if deleted: action = "Removed and archived. Can be restored if this was a mistake."
            elif row["state"] == "report_spam": action = "Flagged as spam in report mode; still visible. Decide whether to keep or remove."
            elif row["state"] in {"failed", "pending"}: action = "Automatic checking failed; still visible. Review manually or retry."
            else: action = "The moderation provider was uncertain; still visible. Decide whether to keep or remove."
            plain.extend([f"{author} — {title}", "Comment:", text, "", "Why: " + row["reason"], action])
            if link: plain.append("Open discussion: " + link)
            plain.extend(["Reference: " + row["id"][:8], ""])
            button = (f'<p><a href="{escape(link, quote=True)}" style="color:#1464b4">Open discussion</a></p>' if link else "")
            items.append(f'''<div style="border:1px solid #dce3e9;border-radius:8px;padding:20px;margin:14px 0">
<p style="margin:0 0 6px;font-weight:bold">{escape(author)}</p>
<p style="margin:0 0 14px;color:#536170;font-size:14px">{escape(title)}</p>
<div style="white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;padding:14px;border-left:3px solid #1464b4">{escape(text)}</div>
<p><strong>Why:</strong> {escape(row['reason'])}</p><p style="color:#536170">{escape(action)}</p>{button}
<p style="font-size:12px;color:#657383">Reference: {escape(row['id'][:8])}</p></div>''')
        if len(rows) > limit:
            more = f"Showing {limit} of {len(rows)}; use the comments tool to review the remaining entries."
            plain.append(more); items.append(f"<p>{escape(more)}</p>")
        sections.append(f'<h2 style="font-size:21px;margin:28px 0 12px">{escape(heading)}</h2>' + "".join(items))

    cards(reviews, "Needs your attention")
    cards(removed, "Removed comments", deleted=True, limit=5)
    if restored_ids:
        count = len(restored_ids)
        notes.append(f"{count} {'comment' if count == 1 else 'comments'} restored by you; approved versions stay visible.")
    if notes:
        plain.extend(["Service notes", *dict.fromkeys(notes), ""])
        sections.append('<h2 style="font-size:21px;margin:28px 0 12px">Service notes</h2>'
                        + "".join(f"<p>{escape(n)}</p>" for n in dict.fromkeys(notes)))
    footer = "No user accounts were automatically blocked. Operational details remain in the audit history."
    plain.append(footer)
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="margin:0;background:#eef2f5;font-family:Arial,sans-serif;color:#182632">
<div style="max-width:640px;margin:24px auto;background:#fff;padding:28px;border-radius:10px">
<p style="color:#1464b4;font-weight:bold;margin:0">{escape(brand)}</p>
<h1 style="font-size:26px;margin:10px 0">Journal comments</h1>
<p style="font-size:18px;font-weight:bold">{escape(summary)}</p>
<p style="font-size:14px;color:#536170">{escape(intro)}</p><p>{escape(mode_text)}</p>
{''.join(sections)}<p style="border-top:1px solid #dce3e9;padding-top:18px;font-size:12px;color:#657383">{escape(footer)}</p>
</div></body></html>'''
    return subject, "\n".join(plain), html
