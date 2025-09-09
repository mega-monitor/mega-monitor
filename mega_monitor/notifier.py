from __future__ import annotations
import csv, io, json, traceback
from datetime import datetime
from typing import Dict, Tuple, Optional, Union
from zoneinfo import ZoneInfo
import requests
from requests import HTTPError

from .config import settings
from .state_manager import logger
from .mega_client import sanitize

SUPPRESS_EMBEDS = 1 << 2  # 4
DEFAULT_TIMEOUT = (3.05, 30)
FAST_TIMEOUT = (0.5, 2)

def format_mentions() -> str:
    return ' '.join(f"<@{uid}>" for uid in settings.mention_user_ids)

def post_webhook(
    content: str = "",
    *,
    files: Optional[Dict[str, Tuple[str, Union[str, bytes], str]]] = None,
    flags: Optional[int] = None,
    fast: bool = False,
    prepend_mentions: bool = False,
) -> Optional[requests.Response]:
    """
    Unified webhook sender.
    - If `files` provided, sends multipart with payload_json.
    - Otherwise sends JSON.
    - `flags` can include SUPPRESS_EMBEDS to disable previews.
    - `fast=True` uses short timeouts for startup/exit paths.
    - `prepend_mentions=True` adds settings.mention_user_ids up top.
    """
    if prepend_mentions:
        m = format_mentions()
        if m:
            content = f"{m}\n{content}"

    payload = {"content": content}
    if flags is not None:
        payload["flags"] = flags

    timeout = FAST_TIMEOUT if fast else DEFAULT_TIMEOUT

    try:
        if files:
            resp = requests.post(
                settings.discord_webhook_url,
                data={"payload_json": json.dumps(payload)},
                files=files,
                timeout=timeout,
            )
        else:
            resp = requests.post(
                settings.discord_webhook_url,
                json=payload,  # JSON so flags are honored
                timeout=timeout,
            )
        resp.raise_for_status()
        return resp

    except HTTPError as e:
        status = e.response.status_code if e.response is not None else None

        if status == 401:
            logger.error("401 Unauthorized: Check DISCORD_WEBHOOK_URL.")
        elif status == 403:
            logger.error("403 Forbidden: Webhook has no permission to post in the channel.")
        elif status == 404:
            logger.error("404 Not Found: Webhook URL invalid/deleted.")
        elif status == 429:
            logger.warning("429 Too Many Requests: rate limited by Discord; try again next run.")
        elif status and 400 <= status < 500:
            logger.error("Client error %s: payload rejected. Check content/URL.", status)
        elif status and 500 <= status < 600:
            logger.error("Server error %s from Discord; will retry next cycle.", status)
        else:
            logger.exception("Unexpected HTTP error sending webhook.")
        return None

    except Exception:
        logger.exception("Non-HTTP error sending webhook.")
        return None

# ---------------- convenience notifiers below ----------------

def notify_discord(name: str, url: str, new_items: list, renamed_items: list, deleted_items: list):
    parts = []
    if new_items: parts.append(f"{len(new_items)} New")
    if renamed_items: parts.append(f"{len(renamed_items)} Renamed")
    if deleted_items: parts.append(f"{len(deleted_items)} Deleted")
    summary = " & ".join(parts) + " Item(s) Detected" if parts else "No Changes"

    now = datetime.now(ZoneInfo(settings.timezone))
    timestamp = now.strftime("%B %d, %Y %I:%M:%S %p %Z")

    # CSV attachment
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['Change','Path','Old Path','New Path','Size'])
    writer.writeheader()
    for f in new_items: writer.writerow({'Change':'NEW','Path':f['path'],'Size':f.get('size')})
    for old,new in renamed_items: writer.writerow({'Change':'RENAMED','Old Path':old,'New Path':new})
    for d in deleted_items: writer.writerow({'Change':'DELETED','Path':d['path']})
    csv_data = output.getvalue()

    # Suppress embed for the URL
    content = f"[{name}]({url}) **{summary}** — {timestamp}"
    files = {"file": (f"{sanitize(name)}.csv", csv_data, "text/csv")}
    resp = post_webhook(
        content,
        files=files,
        flags=SUPPRESS_EMBEDS,
        prepend_mentions=True,
    )
    if resp:
        logger.debug(
            "Discord webhook OK for %s → %d new / %d renamed / %d deleted (status %s)",
            name, len(new_items), len(renamed_items), len(deleted_items), resp.status_code
        )

def notify_error(name: str, exc: Exception):
    tb = traceback.format_exc()
    now = datetime.now(ZoneInfo(settings.timezone))
    timestamp = now.strftime("%B %d, %Y %I:%M:%S %p %Z")
    content = f"[{name}] 🚨 Error — {timestamp}: {exc}"
    post_webhook(
        content,
        files={"file": (f"{sanitize(name)}_error.txt", tb, "text/plain")},
        flags=SUPPRESS_EMBEDS,
        prepend_mentions=True,
    )
    logger.error("Error encountered in %s: %s", name, exc)

def notify_unavailable(name: str, url: str, code: int, reason: str, *, fast: bool = False):
    now = datetime.now(ZoneInfo(settings.timezone))
    timestamp = now.strftime("%B %d, %Y %I:%M:%S %p %Z")
    # Angle brackets also prevent unfurl; flags is the main lever though.
    content = f"[{name}] ⚠️ Link unavailable — {timestamp}\nCode {code}: {reason}\n<{url}>"
    post_webhook(content, flags=SUPPRESS_EMBEDS, fast=fast)
    logger.warning("Unavailable: %s (code=%s) %s", name, code, reason)

def notify_startup_summary(reports, *, fast: bool = False):
    now = datetime.now(ZoneInfo(settings.timezone))
    ts = now.strftime("%B %d, %Y %I:%M:%S %p %Z")
    lines = [f"• [{r.name}] code {r.code}: {r.reason}\n<{r.url}>" for r in reports]
    content = f"⚠️ Startup blocked — {ts}\nNo valid MEGA links found. Details:\n" + "\n".join(lines)
    post_webhook(content, flags=SUPPRESS_EMBEDS, fast=fast)
