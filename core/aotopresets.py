"""Aoto parameter presets: a folder/file browser inside each AOTO group.

Each AOTO group gets a "Пресеты" submenu that browses the on-disk tree under
AOTO_PRESETS_DIR (aoto/presets by default), which mirrors `menus/`:

    aoto/presets/
      parameters.json              optional catalog of parameters for capture
      parameters.example.json      ignored (a template, see below)
      01_Заставка/                 a preset folder (submenu)
        01_зал.json                a preset file (apply button)
        02_ночь.json

A preset file is a SELF-CONTAINED JSON array of parameters (apply needs only
the file, no code and no other config):

    [
      { "name": "Вход",
        "set":  { "path": "/ng_ctrl_sys/globalSettings/setScreenStatus",
                  "key": "type", "value": 0 },
        "get":  { "path": "/ng_ctrl_sys/globalSettings/getScreenStatus",
                  "field": "obj.type" } },
      { "name": "Яркость",
        "set":  { "path": "/ng_ctrl_sys/globalSettings/setBrightness",
                  "key": "brightness", "value": 800 },
        "get":  { "path": "/ng_ctrl_sys/globalSettings/getGlobalSettings",
                  "field": "obj.brightness" } }
    ]

  - applying a preset POSTs every set.body {key: value, **extra} to EVERY
    controller of the current group (aggregated "OK k/m");
  - `get` (optional) is used to CAPTURE the current state into a new preset:
    the value is read from every controller and stored only when the whole
    group agrees; an optional parameter-level `map` ({"read": write}) converts
    read values to write values (e.g. PixelHue-style HDR read/write scales);
  - the catalog for capture is parameters.json (optional; template
    parameters.example.json). It lists which parameters exist and how to read
    them -- the parameter list grows by editing that file, never by code.

Deck actions per folder: apply any preset; "Записать пресет" captures the
current group state into a new file (name is auto-generated - rename it on a
PC); "Новая папка" creates a preset folder. Folders/files are regular disk
content, so they can also be authored/renamed on a PC like menus/.

Catalog/state lives here (cached, refreshed by refresh()); providers only read
caches. HTTP goes through aoto.fire/probe (see core/aoto.py), so presets are
fail-soft like every other Aoto command.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

from . import aoto
from .config import AOTO_PRESETS_DIR
from .constants import After, Kind
from .model import ActionNode, MenuNode

log = logging.getLogger("aotopresets")

_PREFIX = re.compile(r"^\d+[_\-\s]*")            # NN_ ordering prefix
_NEW_PRESET_BASE = "Новый пресет"                 # auto names (rename on a PC later)
_NEW_FOLDER_BASE = "Новая папка"
# Files that are NOT presets: dotfiles, underscore-prefixed, parameters.*
_SKIP = re.compile(r"^(\.|_)|^parameters", re.IGNORECASE)

_lock = threading.RLock()
_tree: dict[str, list[dict]] = {}                 # rel dir -> [entry ...]
_parameters: list[dict] = []                      # catalog for capture
_available = False                                # dir exists and has something usable
_msgs: dict[tuple[str, str], str] = {}            # (group, rel dir) -> last capture text


# --- naming / parsing (pure) -------------------------------------------------
def _label(name: str) -> str:
    return _PREFIX.sub("", name) or name


def _preset_label(filename: str) -> str:
    return _label(Path(filename).stem)


def _is_preset_file(path: Path) -> bool:
    return (path.suffix.lower() == ".json" and not _SKIP.match(path.name))


def parse_preset(data, source: str) -> list[dict]:
    """Normalize a preset body to an applyable parameter list (invalid rows dropped)."""
    if isinstance(data, dict):
        data = data.get("params")
    if not isinstance(data, list):
        log.warning("aotopresets %s: not a JSON array of parameters", source)
        return []
    out: list[dict] = []
    for p in data:
        if not isinstance(p, dict):
            continue
        s = p.get("set")
        if not (isinstance(s, dict) and isinstance(s.get("path"), str) and s["path"]
                and isinstance(s.get("key"), str) and "value" in s):
            continue                       # not applyable -> drop (with a warning below)
        out.append(p)
    if len(out) != len([p for p in data if isinstance(p, dict)]):
        log.warning("aotopresets %s: some parameters lack set.path/key/value and were dropped", source)
    return out


def parse_catalog(data, source: str) -> list[dict]:
    """Catalog = parameters usable for capture: each needs a full set + get spec."""
    if isinstance(data, dict):
        data = data.get("parameters")
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for p in data:
        if not isinstance(p, dict):
            continue
        s, g = p.get("set"), p.get("get")
        if not (isinstance(s, dict) and isinstance(s.get("path"), str) and s["path"]
                and isinstance(s.get("key"), str)):
            continue
        if not (isinstance(g, dict) and isinstance(g.get("path"), str) and g["path"]
                and isinstance(g.get("field"), str)):
            continue
        out.append(p)
    return out


# --- disk catalog ------------------------------------------------------------
def _load_preset_file(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("aotopresets %s unreadable/invalid: %s", path.name, e)
        return []
    return parse_preset(data, str(path))


def _load_catalog() -> list[dict]:
    path = AOTO_PRESETS_DIR / "parameters.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("aotopresets parameters.json invalid: %s", e)
        return []
    return parse_catalog(data, "parameters.json")


def _scan_dir(rel: str) -> list[dict]:
    """Entries of one directory: subfolders and preset files (sorted, no I/O beyond this)."""
    base = AOTO_PRESETS_DIR / rel if rel else AOTO_PRESETS_DIR
    entries: list[dict] = []
    try:
        children = sorted(p for p in base.iterdir() if not _SKIP.match(p.name))
    except FileNotFoundError:
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("aotopresets dir unreadable: %s", e)
        return []
    for p in children:
        if p.is_dir():
            entries.append({"type": "folder", "name": p.name, "label": _label(p.name),
                            "rel": (rel + "/" + p.name) if rel else p.name})
        elif _is_preset_file(p):
            params = _load_preset_file(p)
            if not params:
                continue
            entries.append({"type": "preset", "name": p.name,
                            "label": _preset_label(p.name), "params": params})
    return entries


def _scan_all() -> dict[str, list[dict]]:
    """Build the {rel dir -> entries} map for the whole preset tree."""
    tree: dict[str, list[dict]] = {}

    def walk(rel: str) -> None:
        entries = _scan_dir(rel)
        tree[rel] = entries
        for e in entries:
            if e["type"] == "folder":
                walk(e["rel"])

    walk("")
    return tree


def refresh() -> None:
    """Re-read the preset tree and the capture catalog from disk (start/reload)."""
    global _parameters, _available, _tree
    with _lock:
        try:
            tree = _scan_all()
        except Exception as e:  # noqa: BLE001
            log.warning("aotopresets refresh failed: %s", e)
            tree = {}
        parameters = _load_catalog()
        _tree = tree
        _parameters = parameters
        # Available when there is something to browse OR a way to start one:
        # parameters.json (capture catalog) / the example template / any preset.
        _available = AOTO_PRESETS_DIR.is_dir() and bool(
            parameters or any(tree.values())
            or (AOTO_PRESETS_DIR / "parameters.example.json").is_file())


def parameters() -> list[dict]:
    with _lock:
        return list(_parameters)


def list_dir(rel: str) -> list[dict]:
    with _lock:
        return list(_tree.get(rel, []))


def available() -> bool:
    with _lock:
        return _available


def _next_num(rel: str) -> int:
    """Smallest free NN so a new auto-named item does not collide (1-based)."""
    nums = [int(m.group(0)) for e in list_dir(rel)
            for m in [re.match(r"\d+", e["name"])] if m]
    return (max(nums) + 1) if nums else 1


# --- HTTP helpers -------------------------------------------------------------
def _set_command(param: dict) -> dict | None:
    """The {method, path, body} command a preset parameter applies."""
    s = param["set"]
    return {
        "method": s.get("method", "POST"),
        "path": s["path"],
        "body": {s["key"]: s["value"], **(s.get("extra") or {})},
    }


def _read_command(param: dict) -> dict:
    g = param["get"]
    return {"method": g.get("method", "POST"), "path": g["path"],
            "body": g.get("body") or {},       # some reads need a body, e.g. {"id": 1}
            "response_field": g["field"]}


# --- deck actions (on_press; HTTP outside state.lock) -------------------------
def apply_preset(group: str, params: list[dict]) -> str:
    """Apply every parameter to every controller of the group; "OK k/m" / "ERR ..."."""
    total = ok = 0
    for param in params:
        cmd = _set_command(param)
        if cmd is None:
            continue
        results = aoto.probe(group, cmd)
        total += len(results)
        ok += sum(1 for _a, good, _v in results if good)
    if total == 0:
        return "нет адресов"
    return f"OK {ok}/{total}" if ok == total else f"ERR {total - ok}/{total}"


def _capture_value(group: str, param: dict) -> tuple[bool, object, str]:
    """Read a parameter from the whole group: (ok, value, problem). Value stored only
    when every controller replied and all agree (else a preset would lie)."""
    results = aoto.probe(group, _read_command(param))
    if not results:
        return False, None, "нет адресов"
    if not all(good for _a, good, _v in results):
        return False, None, "ошибка чтения"
    vals = {v for _a, good, v in results if good and v is not None}
    if len(vals) != 1:
        return False, None, "контроллеры расходятся"
    value = next(iter(vals))
    m = param.get("map")
    if isinstance(m, dict):
        value = m.get(str(value), value)
    return True, value, ""


def _preset_item(param: dict, value) -> dict:
    """A captured parameter, self-contained (set with the stored value + get spec)."""
    s, g = param["set"], param["get"]
    set_part = {k: s[k] for k in ("path", "key")}
    for k in ("method", "extra"):
        if k in s:
            set_part[k] = s[k]
    set_part["value"] = value
    get_part = {k: g[k] for k in ("path", "field")}
    if "method" in g:
        get_part["method"] = g["method"]
    item = {"name": param.get("name", "Параметр")}
    if "map" in param:
        item["map"] = param["map"]            # keep so a re-capture maps the same way
    item["set"] = set_part
    item["get"] = get_part
    return item


def capture_preset(group: str, rel: str) -> str:
    """Read the catalog parameters from the group and write a new preset file.

    Auto-named (rename on a PC); returns "" -- the folder re-renders and the
    message appears on the capture button via _capture_label.
    """
    params = parameters()
    if not params:
        _remember(group, rel, "нет параметров.json")
        return ""
    items, skipped = [], []
    for param in params:
        ok, value, problem = _capture_value(group, param)
        if ok:
            items.append(_preset_item(param, value))
        else:
            skipped.append(f"{param.get('name', '?')}: {problem}")
    if not items:
        _remember(group, rel, "нет общих значений")
        return ""
    num = _next_num(rel)
    name = f"{num:02d}_{_NEW_PRESET_BASE} {num}.json"
    target = (AOTO_PRESETS_DIR / rel if rel else AOTO_PRESETS_DIR) / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("aotopresets save %s failed: %s", name, e)
        _remember(group, rel, "не удалось записать")
        return ""
    msg = f"OK {len(items)}"
    if skipped:
        msg += f", {len(skipped)} пропущено"
    _remember(group, rel, msg)
    refresh()                                  # the new preset appears in this folder
    return ""


def make_folder(rel: str) -> str:
    """Create a preset folder (auto-named; rename on a PC). Returns "" (re-render)."""
    num = _next_num(rel)
    name = f"{num:02d}_{_NEW_FOLDER_BASE} {num}"
    try:
        ((AOTO_PRESETS_DIR / rel if rel else AOTO_PRESETS_DIR) / name).mkdir()
    except Exception as e:  # noqa: BLE001
        log.warning("aotopresets mkdir %s failed: %s", name, e)
        return ""
    refresh()
    return ""


def _remember(group: str, rel: str, text: str) -> None:
    with _lock:
        _msgs[(group, rel)] = text[:40]


def _last_msg(group: str, rel: str) -> str:
    with _lock:
        return _msgs.get((group, rel), "")


# --- menu tree (providers; read caches only) ----------------------------------
def group_presets_node(group: str) -> MenuNode | None:
    """The "Пресеты" submenu of one AOTO group; None when the store is empty."""
    if not available():
        return None
    return MenuNode(name="__presets__", path=None, label="Пресеты",
                    provider=_folder_children, context={"group": group, "rel": ""})


def _folder_children(node) -> list:
    group = node.context["group"]
    rel = node.context["rel"]
    out: list = [
        ActionNode(name="__capture__", label=_capture_label(group, rel),
                   kind=Kind.COMMAND, after=After.RERENDER,
                   on_press=lambda g=group, r=rel: capture_preset(g, r)),
        ActionNode(name="__folder__", label="Новая папка", kind=Kind.COMMAND,
                   after=After.RERENDER, on_press=lambda r=rel: make_folder(r)),
    ]
    for entry in list_dir(rel):
        if entry["type"] == "folder":
            out.append(MenuNode(name=entry["name"], path=None, label=entry["label"],
                                provider=_folder_children,
                                context={"group": group, "rel": entry["rel"]}))
        else:
            params = entry["params"]
            out.append(ActionNode(name=entry["name"], label=entry["label"],
                                  kind=Kind.COMMAND, after=After.TEXT,
                                  on_press=lambda g=group, p=params: apply_preset(g, p)))
    return out


def _capture_label(group: str, rel: str) -> str:
    msg = _last_msg(group, rel)
    return f"Записать пресет\n{msg}" if msg else "Записать пресет"
