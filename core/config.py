"""Central configuration. Tweak values here, not scattered through the code."""
from pathlib import Path

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

# --- PDQ Deploy integration -----------------------------------------------
# .pdq buttons shell out to this CLI. Requires an Enterprise license, the PDQ
# background service running, and this server started elevated (as admin).
# The CLI is local-only: PDQ Deploy must be installed on THIS machine.
PDQ_DEPLOY_EXE = r"C:\Program Files\Admin Arsenal\PDQ Deploy\PDQDeploy.exe"
PDQ_TIMEOUT = 60.0         # seconds, for a PDQ CLI call

# --- Colors (bg, fg) as CSS hex; sent to Companion as r/g/b 0-255 over OSC ---
COLORS = {
    "menu":     ("#12233b", "#ffffff"),  # submenu / folder
    "command":  ("#2b2b2b", "#ffffff"),  # script button
    "feedback": ("#0f3d2e", "#8affc1"),  # script button with live output
    "back":     ("#4a1414", "#ffb4b4"),  # navigate up
    "nav":      ("#22303f", "#cfe3ff"),  # paging (prev / next)
    "empty":    ("#000000", "#000000"),  # cleared cell
}
