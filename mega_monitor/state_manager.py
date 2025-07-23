import json
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

def load_previous_state(state_file: Path) -> List[Dict]:
    if state_file.exists():
        data = json.loads(state_file.read_text())
        logging.getLogger(__name__).debug("Loaded %d entries from %s", len(data), state_file)
        return data
    logger.debug("No previous state: %s", state_file)
    return []


def save_state(state: List[Dict], state_file: Path):
    state_file.write_text(json.dumps(state, indent=2))
    logging.debug("Saved %d entries to %s", len(state), state_file)