import io
import csv
import json
import traceback
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

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

    content = f"[{name}]({url}) {mentions}\n**{summary}** — {timestamp} — see attached CSV."
    resp = requests.post(
        settings.discord_webhook_url,
        data={"content": content},
        files={"file": (f"{sanitize(name)}.csv", csv_data, "text/csv")},
        timeout=(3.05, 30)
    )
    logger.debug(
        "Sending Discord notification for %s → %d new / %d renamed / %d deleted",
        name, len(new_items), len(renamed_items), len(deleted_items)
    )
    try:
        resp.raise_for_status()
        logger.debug("Discord webhook accepted for %s (status %s)", name, resp.status_code)
    except Exception:
        logger.exception("Discord webhook failed for %s", name)
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