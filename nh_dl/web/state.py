from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

WEB_STATE_FILE = Path(".nh_dl_web.json")

_VALID_MODES = {"vertical", "single"}
_VALID_FITS = {"width", "height", "original"}
_MAX_UNSTARRED_HISTORY = 15


def default_web_state() -> dict:
    return {
        "library_dir": None,
        "bookmarks": [],
        "progress": {},
        "reader_prefs": {
            "mode": "vertical",
            "fit": "width",
        },
        "search_history": [],
    }


def _normalize_search_history(raw_history: object) -> list[dict]:
    if not isinstance(raw_history, list):
        return []
    seen: set[str] = set()
    cleaned: list[dict] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query or query in seen:
            continue
        seen.add(query)
        starred = bool(item.get("starred", False))
        updated_at = str(item.get("updated_at") or "").strip() or datetime.now(timezone.utc).isoformat()
        cleaned.append({"query": query, "starred": starred, "updated_at": updated_at})

    # Keep all starred items plus at most _MAX_UNSTARRED_HISTORY unstarred items
    result: list[dict] = []
    unstarred_count = 0
    for entry in cleaned:
        if entry["starred"]:
            result.append(entry)
        elif unstarred_count < _MAX_UNSTARRED_HISTORY:
            result.append(entry)
            unstarred_count += 1
    return result


def _normalize_state(raw: object) -> dict:
    state = default_web_state()
    if not isinstance(raw, dict):
        return state

    raw_dir = raw.get("library_dir")
    if isinstance(raw_dir, str) and raw_dir.strip():
        state["library_dir"] = raw_dir.strip()

    raw_bookmarks = raw.get("bookmarks")
    if isinstance(raw_bookmarks, list):
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in raw_bookmarks:
            key = str(item).strip()
            if key and key not in seen:
                seen.add(key)
                cleaned.append(key)
        state["bookmarks"] = cleaned

    raw_progress = raw.get("progress")
    if isinstance(raw_progress, dict):
        cleaned_prog: dict[str, dict] = {}
        for k, v in raw_progress.items():
            key = str(k).strip()
            if not key or not isinstance(v, dict):
                continue
            page = v.get("page")
            if isinstance(page, int) and not isinstance(page, bool) and page >= 1:
                updated_at = str(v.get("updated_at") or "").strip() or datetime.now(timezone.utc).isoformat()
                cleaned_prog[key] = {"page": page, "updated_at": updated_at}
        state["progress"] = cleaned_prog

    raw_prefs = raw.get("reader_prefs")
    if isinstance(raw_prefs, dict):
        if raw_prefs.get("mode") in _VALID_MODES:
            state["reader_prefs"]["mode"] = raw_prefs["mode"]
        if raw_prefs.get("fit") in _VALID_FITS:
            state["reader_prefs"]["fit"] = raw_prefs["fit"]

    state["search_history"] = _normalize_search_history(raw.get("search_history"))
    return state


def load_web_state(state_path: Path = WEB_STATE_FILE) -> dict:
    if not state_path.exists():
        return default_web_state()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return _normalize_state(data)
    except Exception:
        return default_web_state()


def save_web_state(state: dict, state_path: Path = WEB_STATE_FILE) -> dict:
    normalized = _normalize_state(state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(f"{state_path.name}.tmp")
    tmp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, state_path)
    return normalized


def update_web_state(patch: dict, state_path: Path = WEB_STATE_FILE) -> dict:
    current = load_web_state(state_path)
    if not isinstance(patch, dict):
        return current

    if "library_dir" in patch:
        raw_dir = patch["library_dir"]
        if raw_dir is None or (isinstance(raw_dir, str) and not raw_dir.strip()):
            current["library_dir"] = None
        elif isinstance(raw_dir, str):
            current["library_dir"] = raw_dir.strip()

    if isinstance(patch.get("toggle_bookmark"), (str, int)):
        key = str(patch["toggle_bookmark"]).strip()
        if key:
            if key in current["bookmarks"]:
                current["bookmarks"] = [b for b in current["bookmarks"] if b != key]
            else:
                current["bookmarks"].append(key)

    if isinstance(patch.get("bookmarks"), list):
        current["bookmarks"] = patch["bookmarks"]

    if isinstance(patch.get("progress"), dict):
        for k, v in patch["progress"].items():
            key = str(k).strip()
            if not key:
                continue
            if v is None:
                current["progress"].pop(key, None)
            elif isinstance(v, dict) and isinstance(v.get("page"), int) and not isinstance(v.get("page"), bool) and v["page"] >= 1:
                current["progress"][key] = {
                    "page": v["page"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }

    if isinstance(patch.get("reader_prefs"), dict):
        prefs = patch["reader_prefs"]
        if prefs.get("mode") in _VALID_MODES:
            current["reader_prefs"]["mode"] = prefs["mode"]
        if prefs.get("fit") in _VALID_FITS:
            current["reader_prefs"]["fit"] = prefs["fit"]

    now_iso = datetime.now(timezone.utc).isoformat()
    history: list[dict] = list(current.get("search_history", []))

    if isinstance(patch.get("add_search"), str):
        q = patch["add_search"].strip()
        if q:
            existing = next((item for item in history if item["query"] == q), None)
            starred = existing["starred"] if existing else False
            history = [item for item in history if item["query"] != q]
            history.insert(0, {"query": q, "starred": starred, "updated_at": now_iso})

    if isinstance(patch.get("toggle_star_search"), str):
        q = patch["toggle_star_search"].strip()
        if q:
            existing = next((item for item in history if item["query"] == q), None)
            if existing:
                existing["starred"] = not existing["starred"]
                existing["updated_at"] = now_iso
            else:
                history.insert(0, {"query": q, "starred": True, "updated_at": now_iso})

    if isinstance(patch.get("remove_search"), str):
        q = patch["remove_search"].strip()
        if q:
            history = [item for item in history if item["query"] != q]

    current["search_history"] = history
    return save_web_state(current, state_path)
