from __future__ import annotations
import os, sys, logging, asyncio, signal
from pathlib import Path
from typing import Dict, Tuple
from dotenv import load_dotenv
from pydantic import ValidationError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .notifier import notify_startup_summary
from .mega_client import NoValidLinksError


# ── 1. logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger(__name__)


env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file, override=False)
    log.debug("Loaded .env from %s", env_file)


OPTIONALS: Dict[str, Tuple[str, str]] = {
    "LOG_LEVEL": ("INFO", "%s"),
    "TIMEZONE": ("UTC", "%s"),
    "CHECK_INTERVAL_SECONDS": ("3600", "%ss"),
    "MENTION_USER_IDS": ("", "%s"),
}


def announce_defaults() -> None:
    """Log the effective value of each optional variable."""
    for var, (default, fmt) in OPTIONALS.items():
        env_has_value = var in os.environ
        val = os.getenv(var, default)

        if env_has_value:
            log.info("%s set → " + fmt, var, val)
        elif val == "":  # default is empty str
            log.info("%s defaulting to empty", var)
        else:  # any other default
            log.info("%s defaulting to " + fmt, var, val)

        os.environ[var] = val


announce_defaults()


try:
    ZoneInfo(os.environ["TIMEZONE"])
except ZoneInfoNotFoundError:
    log.warning("TIMEZONE '%s' invalid → falling back to UTC", os.environ["TIMEZONE"])
    os.environ["TIMEZONE"] = "UTC"


REQUIRED_KEYS = ["DISCORD_WEBHOOK_URL"]
REQUIRED_PREFIXES = ["MEGA_LINK_"]

missing: list[str] = []

for key in REQUIRED_KEYS:
    if not os.getenv(key):
        missing.append(key)

for pfx in REQUIRED_PREFIXES:
    if not any(k.startswith(pfx) for k in os.environ):
        missing.append(f"{pfx}*")

if missing:
    log.critical(
        "Required variable%s missing → %s",
        "" if len(missing) == 1 else "s",
        ", ".join(missing),
    )
    asyncio.run(asyncio.Event().wait())

try:
    from .runner import run_monitor
except ValidationError as exc:
    missing, invalid = [], []
    for err in exc.errors():
        key = err["loc"][0].upper()
        (missing if err["type"] == "missing" else invalid).append(key)
    if missing:
        log.critical("Missing env vars: %s", ", ".join(missing))
    if invalid:
        log.critical("Invalid env var values: %s", ", ".join(invalid))
    asyncio.run(asyncio.Event().wait())


async def _main() -> None:
    await run_monitor()


async def idle_until_signaled() -> None:
    """Block until SIGTERM/SIGINT; works in containers."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            def _handler(signum, frame):
                try:
                    loop.call_soon_threadsafe(stop.set)
                except RuntimeError:
                    pass
            signal.signal(sig, _handler)

    await stop.wait()

if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except NoValidLinksError as e:
        log.critical("Configuration error: No valid MEGA links")
        notify_startup_summary(e.reports, fast=True)
        asyncio.run(idle_until_signaled())
        sys.exit(0)