import asyncio
from pathlib import Path
import signal
import time
import logging

from .config import settings
from .mega_client import parse_folder_url, base64_to_a32, get_nodes, decrypt_node, build_paths
from .state_manager import load_previous_state, save_state
from .notifier import notify_discord, notify_error
from .mega_client import sanitize
from .mega_client import get_mega_links

logger = logging.getLogger(__name__)


def _setup_signal_handlers(loop):
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, loop.stop)
        except NotImplementedError:
            # Windows can't register these handlers — ignore
            pass


async def monitor_folder(name: str, url: str, state_dir: Path):
    start_ts = time.perf_counter()
    state_file = state_dir / f"{sanitize(name)}.json"
    try:
        root, key = parse_folder_url(url)
        shared_key = base64_to_a32(key)
        nodes = get_nodes(root)
        all_nodes = [decrypt_node(n, shared_key) for n in nodes]
        current = build_paths(all_nodes, root)
        previous = load_previous_state(state_file)

        prev_map = {e['h']: e for e in previous}
        curr_map = {e['h']: e for e in current}

        new_items = [curr_map[h] for h in curr_map if h not in prev_map]
        renamed = [(prev_map[h]['path'], curr_map[h]['path']) for h in curr_map if h in prev_map and curr_map[h]['path'] != prev_map[h]['path']]
        deleted = [prev_map[h] for h in prev_map if h not in curr_map]

        if new_items or renamed or deleted:
            notify_discord(name, url, new_items, renamed, deleted)
            save_state(current, state_file)
            logger.info(
                "%s → %d new / %d renamed / %d deleted (state saved)",
                name, len(new_items), len(renamed), len(deleted)
            )
        else:
            # use INFO so it’s visible at the default log level
            logger.info("%s – no changes detected", name)
    except Exception as e:
        logger.exception(f"Error monitoring {name}")
        notify_error(name, e)
    finally:
        duration = time.perf_counter() - start_ts
        logger.debug("%s check completed in %.2f s", name, duration)
        
async def run_monitor():
    """
    Main entrypoint: periodically checks MEGA links and notifies via Discord.
    Gracefully handles exit signals and cancellation.
    """
    # configure logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # ensure data directory exists
    settings.state_dir.mkdir(parents=True, exist_ok=True)

    # load links
    links = get_mega_links()
    logger.info("Starting monitor – %d folders, interval=%ds",
                len(links), settings.check_interval_seconds)

    loop = asyncio.get_running_loop()
    _setup_signal_handlers(loop)

    try:
        while True:
            # create tasks for each link
            tasks = [
                monitor_folder(link['name'], link['url'], settings.state_dir)
                for link in links
            ]
            # run them concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # log any errors
            for res in results:
                if isinstance(res, Exception):
                    notify_error(getattr(res, 'name', 'Unknown'), res)
            logger.info("Run completed — sleeping for %d s", settings.check_interval_seconds)
            await asyncio.sleep(settings.check_interval_seconds)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutdown requested, exiting monitor loop.")
    finally:
        logger.info("Monitor stopped.")

