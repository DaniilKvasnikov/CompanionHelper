"""Central configuration.

Values defined here are the DEFAULTS shared by every machine through git.
Real per-machine values are NOT edited here -- they live in a git-ignored
`config.local.json` next to the project root (copy of
`config.local.example.json`), read once at import time and applied on top of
these defaults (see the block at the bottom of this file). Keep editing the
defaults here when a knob should change for everyone.
"""
import json
import logging
from pathlib import Path

from .constants import Kind

# --- Companion connection -------------------------------------------------
# All button updates (text + colors) are pushed to Companion's OSC listener
# over UDP. Companion must have OSC control enabled on this host/port.
OSC_HOST = "127.0.0.1"
OSC_PORT = 12321

# --- This server ----------------------------------------------------------
HOST = "0.0.0.0"
PORT = 7878

# The Companion pages the physical decks are mapped to -- one page per deck
# (every button of a deck POSTs its own page number, and all menu state is kept
# per page, so two decks can sit on different menus at the same time). Every
# page listed here is drawn on startup, so a second deck is not blank until its
# first press. Add a machine's extra deck pages in config.local.json, e.g.
# ["1", "2"].
DECK_PAGES = ["1"]

# --- Deck geometry (Stream Deck XL) --------------------------------------
GRID_ROWS = 4          # rows 0..3
GRID_COLS = 8          # cols 0..7
NAV_ROW = 3            # bottom row is reserved for navigation (Back / paging)

# --- Menus / scripts ------------------------------------------------------
# Root of the on-disk menu tree. Folders = submenus, files = command buttons.
MENUS_DIR = Path(__file__).resolve().parent.parent / "menus"

SCRIPT_TIMEOUT = 15.0      # seconds, for command buttons
FEEDBACK_TIMEOUT = 5.0     # seconds, for feedback (.fb) scripts
FEEDBACK_INTERVAL = 5.0    # seconds between feedback polls of the active menu

# --- Progress countdown ---------------------------------------------------
# Companion custom variable $(custom:<PROGRESS_VAR>) is kept updated with a
# 0..100 progress value toward the next feedback refresh, so buttons on
# auto-updating pages can show a progress bar. See core/progress.py.
PROGRESS_VAR = "Progress"
PROGRESS_TICK = 1.0        # seconds between progress updates

# --- PDQ Deploy integration -----------------------------------------------
# .pdq buttons DEPLOY via this CLI (needs Enterprise license, PDQ background
# service running, and this server started elevated/as admin). The CLI is
# local-only. Package/target-list names are READ from PDQ's SQLite database,
# because the CLI has no command to enumerate packages or target lists.
PDQ_DEPLOY_EXE = r"C:\Program Files (x86)\Admin Arsenal\PDQ Deploy\PDQDeploy.exe"
PDQ_DB_PATH = r"C:\ProgramData\Admin Arsenal\PDQ Deploy\Database.db"
PDQ_TIMEOUT = 60.0         # seconds, for a PDQ CLI call
# The status page's PDQ panel shows the deployment journal (running + recent
# tasks). Reading it copies the DB (see pdq._connect), so it runs on its own,
# slower interval than the other panels.
PDQ_STATUS_INTERVAL = 5.0  # seconds between journal reads while a page watches
PDQ_STATUS_LIMIT = 8       # how many recent deployments to show

# --- PC browser (dynamic menu from the active PDQ target list) ------------
# Optional aliases file: lines "ip = alias". An aliased host shows its alias
# above the ip on the deck and sorts by the alias. See core/pcbrowser.py.
PC_ALIASES_FILE = Path(__file__).resolve().parent.parent / "pc_aliases.txt"

PING_INTERVAL = 15.0       # seconds between ping sweeps of the active list
PING_TIMEOUT_MS = 800      # per-host ping wait
PING_WORKERS = 16          # parallel pings

# Ping status colors for PC buttons (bg, fg)
PC_UP = ("#12421d", "#8affa0")       # green  - responded
PC_DOWN = ("#4a1414", "#ff9a9a")     # red    - no reply
PC_UNKNOWN = ("#2b2b2b", "#cccccc")  # gray   - not pinged yet
PC_OFF = ("#161616", "#5a5a5a")      # dim    - toggled out of the PDQ deploy set

# --- Aoto LED-processor control (dynamic menu over HTTP) ------------------
# Groups are files in AOTO_GROUPS_DIR (one controller host:port per line);
# commands are shared across groups and defined in AOTO_COMMANDS_FILE. A
# command press fires an HTTP request to every controller in the group. A
# command with a "response_field" is polled every AOTO_POLL_INTERVAL and its
# value shown on the button (aggregated across the group). See core/aoto.py.
AOTO_DIR = Path(__file__).resolve().parent.parent / "aoto"
AOTO_GROUPS_DIR = AOTO_DIR / "groups"
AOTO_COMMANDS_FILE = AOTO_DIR / "commands.json"
AOTO_HTTP_TIMEOUT = 4.0      # seconds, per controller request
AOTO_POLL_INTERVAL = 10.0    # seconds between status polls
AOTO_WORKERS = 16            # parallel requests within a group

# --- Aoto brightness control (a "Управление яркостью" submenu per group) ---
# Added to each AOTO group when the status command named below exists (it also
# READS the current brightness). The +/- buttons read each controller's current
# brightness via that status command, shift it by the current step, clamp to
# [AOTO_BRIGHTNESS_MIN, per-group limit], and write it back per controller via
# AOTO_SET_BRIGHTNESS_PATH (body {AOTO_SET_BRIGHTNESS_KEY: value}). The ×2 / ÷2
# buttons change the (AOTO-wide) step. See core/aoto.py.
AOTO_BRIGHTNESS_STATUS_LABEL = "Яркость"   # the status command that reads brightness
AOTO_SET_BRIGHTNESS_PATH = "/ng_ctrl_sys/globalSettings/setBrightness"
AOTO_SET_BRIGHTNESS_KEY = "brightness"     # POST body is {this key: target value}
AOTO_BRIGHTNESS_STEP = 50                  # initial step; the ×2 / ÷2 buttons change it
AOTO_BRIGHTNESS_MIN = 0                    # floor when stepping down
AOTO_BRIGHTNESS_LIMIT_DEFAULT = 1500       # max brightness for a group with no override below
AOTO_BRIGHTNESS_LIMITS = {                 # per-group ceiling; key = group label
    # "стена":   1500,
    # "потолок": 1000,
}
# Ceiling priority: the group-file directive (AOTO_BRIGHTNESS_MAX_DIRECTIVE in
# aoto/groups/*.txt) > AOTO_BRIGHTNESS_LIMITS[group] > AOTO_BRIGHTNESS_LIMIT_DEFAULT.
AOTO_BRIGHTNESS_PERCENT = 5                # "Темнее/Ярче 5%" buttons: % of the group ceiling
AOTO_BRIGHTNESS_MAX_DIRECTIVE = "@max"     # group-file line, e.g. "@max = 1500"

# --- Aoto Dynamic Range / HDR control (a "Dynamic Range" submenu per group) ---
# Added to each AOTO group when the status command named below exists. Each mode
# button POSTs AOTO_SET_HDR_PATH with body {AOTO_SET_HDR_KEY: value,
# **AOTO_SET_HDR_EXTRA}. NOTE: these hdrSetting *write* values (SDR=2/HLG=3/PQ=4)
# differ from the *read* scale in commands.json (SDR=1/HLG=2/PQ=3) -- verify both
# against your firmware. See core/aoto.py.
AOTO_HDR_STATUS_LABEL = "HDR"   # the status command whose presence enables the submenu
AOTO_SET_HDR_PATH = "/ng_ctrl_sys/globalSettings/setHDR"
AOTO_SET_HDR_KEY = "hdrSetting"                                  # the varied body field
AOTO_SET_HDR_EXTRA = {"maximumBrightness": 10000, "coefficient": 1}  # fixed body fields
AOTO_HDR_MODES = [              # (button label, hdrSetting value)
    ("SDR", 2),
    ("HLG", 3),
    ("PQ", 4),
]

# --- Aoto presets (a folder/file browser of parameter presets) -------------
# Each AOTO group gets a "Пресеты" submenu browsing the on-disk tree under
# AOTO_PRESETS_DIR, which mirrors menus/: folders = preset groups, *.json files
# = presets. A preset file is a SELF-CONTAINED JSON list of parameters, each
# { "name", "set": {path, key, value, [method], [extra]}, "get": {path, field} }
# -- apply POSTs every set.body {key: value, **extra} to every controller of
# the group. "get" (optional) is used to CAPTURE the current state into a new
# preset. parameters.json (optional; template parameters.example.json) lists
# the available parameters for capture -- add new ones there as the parameter
# list grows (no code changes). See core/aotopresets.py.
AOTO_PRESETS_DIR = AOTO_DIR / "presets"

# --- PixelHue Q8 LED-processor control (an "PixelHue" tab over HTTP) -------
# One device (a Q8/P10/P20/P80 node). Auth is a JWT (HS256, payload {SN},
# secret = startTime from node/open-detail) rebuilt automatically after a
# device reboot (HTTP 401); nothing to configure. All commands go through the
# /unico/v1 namespace (a superset: the documented /pixelhue/v1 404s on
# layers/window|zorder). Screens are read from the device (MVR/multi-viewer
# screens -- screenIdObj.type in PIXELHUE_SKIP_SCREEN_TYPES -- are dropped);
# per-screen Take/Cut/Freeze/FTB buttons plus global FTB/Freeze toggles and a
# preset list are built from the caches a background poller keeps fresh.
# See core/pixelhue.py and PIXELHUE_API_GUIDE.md.
PIXELHUE_HOST = "192.168.200.161"   # node address (override per machine in config.local.json)
PIXELHUE_PORT = 8088
PIXELHUE_NODE_ID = 1                # nodeId for node/open-detail + node/detail
PIXELHUE_TIMEOUT = 5.0              # seconds, per HTTP request
PIXELHUE_POLL_INTERVAL = 10.0       # seconds between node/screen/preset polls
PIXELHUE_SKIP_SCREEN_TYPES = (8,)   # screens to hide: 8 = MVR (multi-viewer); real outputs are type 2
PIXELHUE_TAKE_TIME_MS = 500         # Take / preset-apply transition fade (ms); Cut is instant
PIXELHUE_FTB_TIME_MS = 500          # FTB fade time (ms)
PIXELHUE_PRESET_TARGET_REGION = 2   # where presets load: 2 = program, 4 = preview

# --- Touch (TouchDesigner: the deck buttons ARE the client's buttons) ------
# The "Touch" tab has no hardcoded content: a TouchDesigner client registers
# itself and sets its buttons over HTTP (POST /touch/buttons) and the tab grows
# one submenu per live client. Pressing a button fires ONE fire-and-forget OSC
# message to that client's host:port/address with the button id as a string
# argument, so the press is proxied back into TouchDesigner. Clients must ping
# (POST /touch/ping); one that has been silent for TOUCH_CLIENT_TIMEOUT seconds
# is dropped and the deck is redrawn, so a closed .toe leaves no dead buttons.
# The host/port/address below are only DEFAULTS for a client that sends none.
# See core/touch.py and touch/client.example.py.
TOUCH_OSC_HOST = "127.0.0.1"
TOUCH_OSC_PORT = 7777
TOUCH_OSC_ADDRESS = "/touch"    # OSC address a press is sent to by default
TOUCH_CLIENT_TIMEOUT = 30.0     # drop a client silent for this long (seconds)
TOUCH_SWEEP_INTERVAL = 5.0      # how often the sweeper looks for dead clients

# --- Generic OSC buttons (an "OSC" tab) -----------------------------------
# An "OSC" tab for buttons that fire an arbitrary OSC message. Groups are files
# in OSC_BUTTONS_GROUPS_DIR, one "label = /address arg arg" per line, so each
# button carries its own address and arguments (unlike the Touch tab, where the
# address belongs to the group and the argument is always a filename). A group
# may retarget with "@host =" / "@port =" lines; otherwise it uses the defaults
# below. The defaults point at oscctl (github.com/DaniilKvasnikov/oscctl), whose
# addresses are operator path + parameter name. See core/osc_buttons.py.
OSC_BUTTONS_DIR = Path(__file__).resolve().parent.parent / "osc"
OSC_BUTTONS_GROUPS_DIR = OSC_BUTTONS_DIR / "groups"
OSC_BUTTONS_HOST = "127.0.0.1"
OSC_BUTTONS_PORT = 7000

# --- FreeFileSync sync jobs (a "Sync" tab) --------------------------------
# Each job is a (label, path-to-.ffs_batch) pair shown as a button; pressing it
# runs `FFS_EXE <path>` and shows the result. See core/ffs.py.
FFS_EXE = r"C:\Program Files\FreeFileSync\FreeFileSync.exe"
FFS_TIMEOUT = 600.0        # seconds; a sync can take a while
FFS_JOBS = [
    # ("Фото", r"D:\sync\photo.ffs_batch"),
    # ("Документы", r"D:\sync\docs.ffs_batch"),
]

# --- Develop tab (pull latest changes + restart the server) ---------------
# A "Develop" tab whose button runs `git pull` in PROJECT_ROOT and, on success,
# restarts this process so the new code takes effect. See core/develop.py.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GIT_PULL_TIMEOUT = 60.0    # seconds, for the git pull
RESTART_DELAY = 1.5        # seconds after a pull before restarting (lets the deck render)

# --- Web status page -------------------------------------------------------
# A READ-ONLY page in a browser (GET /) showing the live state of every knob the
# deck can turn: the Aoto parameters of every group, the PixelHue flags/screens,
# and the ping status of the active PDQ list's PCs. The page polls GET /status
# (a JSON snapshot) once a second; the snapshot itself is rebuilt by a background
# thread that re-reads the devices every WEB_REFRESH_INTERVAL seconds -- but ONLY
# while a page is actually watching (a request within WEB_IDLE_TIMEOUT), so a
# closed tab costs nothing. Nothing on the page writes to a device. The page
# markup lives in WEB_PAGE and is re-read per request, so it can be edited
# without restarting the server. See core/webstatus.py.
WEB_PAGE = PROJECT_ROOT / "web" / "index.html"
WEB_LOGS_PAGE = PROJECT_ROOT / "web" / "logs.html"
WEB_REFRESH_INTERVAL = 2.0   # seconds between device reads while a page watches
WEB_IDLE_TIMEOUT = 15.0      # seconds after the last page request before reads stop

# How many distinct problems core/diag.py keeps for the log window (GET /logs).
# Each entry is one open problem with a repeat counter, so this is plenty.
DIAG_MAX = 200

# --- Colors (bg, fg) as CSS hex; sent to Companion as r/g/b 0-255 over OSC ---
COLORS = {
    Kind.MENU:     ("#12233b", "#ffffff"),  # submenu / folder
    Kind.COMMAND:  ("#2b2b2b", "#ffffff"),  # script button
    Kind.FEEDBACK: ("#0f3d2e", "#8affc1"),  # script button with live output
    Kind.BACK:     ("#4a1414", "#ffb4b4"),  # navigate up
    Kind.HOME:     ("#153a3a", "#a9f0e6"),  # jump to the root menu
    Kind.NAV:      ("#22303f", "#cfe3ff"),  # paging (prev / next)
    Kind.EMPTY:    ("#000000", "#000000"),  # cleared cell
}

# --- Machine-local overrides ----------------------------------------------
# Every machine may differ (Companion page number, PDQ/FFS install paths, OSC
# endpoints, sync jobs, ...). Editing those in THIS file would make every
# `git pull` on another machine conflict. Instead, each machine keeps its own
# copy of config.local.example.json as config.local.json (git-ignored); this
# file is read once at import time and its values REPLACE the defaults above,
# by name. Keys that are absent fall back to these defaults; keys that start
# with "_" are notes and are ignored. A missing/invalid file is harmless.
_LOCAL_CONFIG_FILE = PROJECT_ROOT / "config.local.json"
_OVERRIDABLE = {  # names a local file may override (uppercase data constants)
    n for n, v in globals().items()
    if n.isupper() and not n.startswith("_") and not isinstance(v, type)
}


def _read_local_config(path: Path, source: str = "config.local.json") -> dict:
    """Read a local-override JSON object; {} on absence, invalid content, or errors."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001
        logging.getLogger("config").warning("%s unreadable: %s", source, e)
        return {}
    try:
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("config").warning("%s is not valid JSON: %s", source, e)
        return {}
    if not isinstance(data, dict):
        logging.getLogger("config").warning("%s must be a JSON object of config names", source)
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}  # drop notes


def apply_local_overrides(overrides: dict, into: dict | None = None,
                          source: str = "config.local.json") -> list[str]:
    """Replace config constants named in `overrides` inside `into` (default: this
    module's globals). Unknown names are logged and skipped, so a typo in the
    local file never silently breaks a knob. Returns the applied names."""
    into = globals() if into is None else into
    applied: list[str] = []
    for name, value in overrides.items():
        if name not in _OVERRIDABLE:
            logging.getLogger("config").warning(
                "%s: ignoring unknown or non-config key %r", source, name)
            continue
        into[name] = value
        applied.append(name)
    return applied


_local = _read_local_config(_LOCAL_CONFIG_FILE)
_applied = apply_local_overrides(_local)
if _applied:
    logging.getLogger("config").info(
        "local overrides from config.local.json: %s", ", ".join(sorted(_applied)))
