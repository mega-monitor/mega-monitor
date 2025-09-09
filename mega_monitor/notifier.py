import io
import csv
import json
import traceback
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from requests.exceptions import HTTPError

from .config import settings
from .mega_client import sanitize

logger = logging.getLogger(__name__)

def format_mentions() -> str:
    return ' '.join(f"<@{uid}>" for uid in settings.mention_user_ids)


def notify_discord(name: str, url: str, new_items: list, renamed_items: list, deleted_items: list):
    mentions = format_mentions()
    parts = []
    if new_items: parts.append(f"{len(new_items)} New")
    if renamed_items: parts.append(f"{len(renamed_items)} Renamed")
    if deleted_items: parts.append(f"{len(deleted_items)} Deleted")
    summary = " & ".join(parts) + " Item(s) Detected"
    now = datetime.now(ZoneInfo(settings.timezone))
    timestamp = now.strftime("%B %d, %Y %I:%M:%S %p %Z")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['Change','Path','Old Path','New Path','Size'])
    writer.writeheader()
    for f in new_items: writer.writerow({'Change':'NEW','Path':f['path'],'Size':f['size']})
    for old,new in renamed_items: writer.writerow({'Change':'RENAMED','Old Path':old,'New Path':new})
    for d in deleted_items: writer.writerow({'Change':'DELETED','Path':d['path']})
    csv_data = output.getvalue()

    content = f"{mentions}\n[{name}]({url}) **{summary}** — {timestamp}"
    payload = {
        "content": content,
        "flags": 4  # suppress link previews
    }

    try:
        resp = requests.post(
            settings.discord_webhook_url,
            data={"payload_json": json.dumps(payload)},
            files={
                "file": (
                    f"{sanitize(name)}.csv",
                    csv_data,
                    "text/csv"
                )
            },
            timeout=(3.05, 30)
        )
        resp.raise_for_status()
        logger.debug(
            "Discord webhook accepted for %s → %d new / %d renamed / %d deleted (status %s)",
            name, len(new_items), len(renamed_items), len(deleted_items), resp.status_code
        )

    except HTTPError as e:
        status = e.response.status_code if e.response is not None else None

        if status == 401:
            logger.error(
                "401 Unauthorized: Invalid webhook URL or credentials. Please check your DISCORD_WEBHOOK_URL."
            )
            return

        elif status == 403:
            logger.error(
                "403 Forbidden: The webhook exists but you don’t have permission to post. " 
                "Verify the webhook’s channel permissions."
            )
            return

        elif status == 404:
            logger.error(
                "404 Not Found: The webhook URL is invalid or has been deleted. "
                "Please verify the URL."
            )
            return

        elif status == 429:
            logger.warning(
                "429 Too Many Requests: rate limited by Discord. Discord will auto‑retry this webhook."
            )
            return

        elif 400 <= status < 500:
            logger.error(
                "Client error %s: Payload rejected. Check your message content and webhook URL.",
                status
            )
            return

        elif 500 <= status < 600:
            logger.error(
                "Server error %s: Discord is having issues. "
                "This notification will retry on the next run.",
                status
            )
            return

        else:
            # Fallback for anything unexpected
            logger.exception(
                "Unexpected HTTP error %s when sending to Discord webhook for %s.",
                status, name
            )
            raise

    except Exception:
        logger.exception("Non-HTTP error sending Discord notification for %s", name)
        raise


def notify_error(name: str, exc: Exception):
    tb = traceback.format_exc()
    now = datetime.now(ZoneInfo(settings.timezone))
    timestamp = now.strftime("%B %d, %Y %I:%M:%S %p %Z")
    content = f"[{name}] {format_mentions()} 🚨 Error — {timestamp}: {exc}"
    logger.error("Error encountered in %s: %s", name, exc)
    requests.post(
        settings.discord_webhook_url,
        data={"content": content},
        files={"file": (f"{sanitize(name)}_error.txt", tb, "text/plain")},
        timeout=(3.05, 30)
    )
    
def notify_unavailable(name: str, url: str, code: int, reason: str):
    now = datetime.now(ZoneInfo(settings.timezone))
    timestamp = now.strftime("%B %d, %Y %I:%M:%S %p %Z")
    content = f"[{name}] ⚠️ Link unavailable — {timestamp}\n" \
              f"Code {code}: {reason}\n{url}"
    logger.warning("Unavailable: %s (%s) %s", name, code, reason)
    requests.post(settings.discord_webhook_url, data={"content": content}, timeout=(3.05, 30))
    
def _post_webhook(content: str, timeout=(3.05, 30)):
    try:
        requests.post(
            settings.discord_webhook_url,
            data={"content": content},
            timeout=timeout,
        )
    except Exception as e:
        logger.debug("Startup webhook send skipped: %s", e)

def notify_startup_summary(reports, *, fast: bool = False):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo(settings.timezone))
    ts = now.strftime("%B %d, %Y %I:%M:%S %p %Z")
    lines = [f"• [{r.name}] code {r.code}: {r.reason}\n{r.url}" for r in reports]
    content = (
        f"⚠️ Startup blocked — {ts}\n"
        "No valid MEGA links found. Details:\n" + "\n".join(lines)
    )
    timeout = (0.5, 2) if fast else (3.05, 30)
    _post_webhook(content, timeout=timeout)