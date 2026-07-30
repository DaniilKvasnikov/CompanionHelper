"""Central configuration. Tweak values here, not scattered through the code."""
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

# The Companion page number the physical deck is mapped to. Used to draw the
# root menu on startup before any button is pressed.
DEFAULT_PAGE = "1"

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

# --- Touch (TouchDesigner control over OSC) -------------------------------
# A "Touch" tab. Groups are files in TOUCH_GROUPS_DIR (one "label = filename"
# per line); pressing a button fires ONE OSC message to TouchDesigner at
# TOUCH_OSC_HOST:TOUCH_OSC_PORT with the button's filename as a string argument.
# Each group has its own OSC address via an "@address = /path" line in its file;
# groups without one fall back to TOUCH_OSC_ADDRESS below. See core/touch.py.
TOUCH_DIR = Path(__file__).resolve().parent.parent / "touch"
TOUCH_GROUPS_DIR = TOUCH_DIR / "groups"
TOUCH_OSC_HOST = "127.0.0.1"
TOUCH_OSC_PORT = 7777
TOUCH_OSC_ADDRESS = "/file"   # default OSC address when a group sets no @address

# --- Develop tab (pull latest changes + restart the server) ---------------
# A "Develop" tab whose button runs `git pull` in PROJECT_ROOT and, on success,
# restarts this process so the new code takes effect. See core/develop.py.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GIT_PULL_TIMEOUT = 60.0    # seconds, for the git pull
RESTART_DELAY = 1.5        # seconds after a pull before restarting (lets the deck render)

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
