import json
from pathlib import Path

STATE_FILE = Path(".nhentai_cli.json")

DEFAULT_STATE = {
    "input": "",
    "output": "./downloads",
    "folder_name": "both",
    "format": "image",
    "concurrency": 5,
}


def load_state(state_path: Path = STATE_FILE) -> dict:
    state = dict(DEFAULT_STATE)
    if not state_path.exists():
        return state
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in DEFAULT_STATE:
                if key in data and data[key] is not None:
                    state[key] = data[key]
    except Exception:
        pass
    return state


def save_state(config: dict, state_path: Path = STATE_FILE) -> None:
    current = load_state(state_path)
    if config.get("input") is not None:
        current["input"] = str(config["input"])
    if config.get("output") is not None:
        current["output"] = str(config["output"])
    if config.get("folder_name") in ("both", "title", "code"):
        current["folder_name"] = config["folder_name"]
    if config.get("format") in ("image", "pdf", "both"):
        current["format"] = config["format"]
    if isinstance(config.get("concurrency"), int) and config["concurrency"] > 0:
        current["concurrency"] = config["concurrency"]

    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception:
        pass
