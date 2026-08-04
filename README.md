# CompanionHelper

A modular, script-backed menu system for an [Elgato Stream Deck](https://www.elgato.com/stream-deck) driven through [Bitfocus Companion](https://bitfocus.io/companion).

The `menus/` folder tree *is* the menu hierarchy: folders become submenus and files become buttons. A small FastAPI service renders that hierarchy onto the deck and runs the backing scripts when buttons are pressed — including deploying software to remote machines via [PDQ Deploy](https://www.pdq.com/pdq-deploy/).

## The core idea: dumb deck, smart server

Companion's remote API can change a button's **visuals** (text, colors) but never its **action**. That makes dynamic, drill-in submenus impossible to build on Companion's side. So this project inverts the responsibility:

Every button on the controlled page is configured in Companion to send the *same* generic `POST /press` with its own `page/row/col`. The server owns all state and logic: it resolves what that coordinate means in the current menu, acts on it, and then re-pushes styles to the deck to reflect the new view.

Two transports, opposite directions:

- **Presses come in over HTTP** — Companion → this server (`POST /press`).
- **Button visuals go out over OSC/UDP** — this server → Companion's OSC listener, fire-and-forget for speed (a redraw diffs against the last-rendered state and pushes only the cells that changed).

## What one press does

1. Deck button → `POST /press?page&row&col`.
2. The dispatcher resolves the current menu, maps the cell to a node, and acts:
   - **submenu** → drill in and redraw;
   - **back / prev / next** → adjust navigation and redraw;
   - **command / feedback button** → run its script and write the result onto that button.
3. Redraw pushes only the changed cells back to Companion over OSC.

## Features

- **Filesystem-defined menus** — build your deck by creating folders and script files; no code changes needed. `POST /reload` rebuilds the tree from disk.
- **Command buttons** — any `.py`, `.ps1`, `.bat`, `.cmd`, `.sh`, or executable; the script's first stdout line is shown on the button.
- **Feedback buttons** (`*.fb.py`) — polled on an interval and on menu entry, with stdout streamed to the button text (e.g. a live clock or CPU meter).
- **PDQ Deploy integration** — deploy packages to specific PCs or whole target lists straight from the deck. Package and target-list names are read from PDQ's SQLite database; deploys run through `PDQDeploy.exe`.
- **Dynamic "PC" menu** — one button per host in the active PDQ target list, colored live by ping status; pick a host, then a package, to deploy to that single machine.
- **Batch "PDQ" menu** — pick the active list, toggle individual hosts in or out, choose a scope (whole list vs. enabled hosts), then deploy a package to the whole selection in one call.
- **"AOTO" LED-processor menu** — control [Aoto](https://www.aoto.com/) video processors over HTTP, grouped by file. Pick a group, then a command; the request fires to every controller in the group at once. Commands that return a status (e.g. current display mode) show the value on the button, aggregated across the group and refreshed in the background.
- **"Touch" menu** — trigger clips/files in [TouchDesigner](https://derivative.ca/) over OSC, grouped by file. Pick a group, then a button; each press fires one OSC message (default `127.0.0.1:7777`) carrying the button's filename. Each group targets its own OSC address (an `@address = /path` line in the group file), so different groups can drive different things. The tab also has top-level buttons (`file`/`base`/`fps`) that fire a no-argument OSC message to an address named after them.
- **"Sync" menu** — run [FreeFileSync](https://freefilesync.org/) batch jobs from the deck. Configure jobs as `(label, path-to-.ffs_batch)` pairs; each press runs `FreeFileSync.exe` on that batch and shows the result.
- **"Develop" menu** — a single button that runs `git pull` on the project and restarts the server so the new code takes effect, straight from the deck.
- **Progress variable** — a Companion custom variable `$(custom:Progress)` filled 0→100 as the next auto-refresh approaches, so an auto-updating page can show a progress bar.

## Menu tree conventions

Naming under `menus/` controls the structure:

| Name                | Becomes                                                        |
| ------------------- | ------------------------------------------------------------- |
| `01_lights/`        | a **submenu** (folder)                                         |
| `01_on.py`          | a **command button** (first stdout line shown on press)       |
| `01_cpu.fb.py`      | a **feedback button** (polled; stdout → button text)          |
| `01_install.pdq`    | a **PDQ Deploy button** (a JSON config, not an executable)     |

A leading `NN_` prefix only controls ordering and is stripped from the displayed label. A button script runs with its own folder as the working directory.

A `.pdq` button is a small JSON config, for example:

```json
{ "package": "Install", "targets": ["PC1", "PC2"] }
```

```json
{ "package": "Install", "target_list": "All" }
```

The grid is a fixed 8×4 (Stream Deck XL): content fills the top three rows, and the bottom row is reserved for **Back** and **Prev/Next** paging when applicable.

## Requirements

- Python 3.10+
- Bitfocus Companion with **OSC control enabled** (the server sends visuals to `127.0.0.1:12321` by default).
- The deck's buttons configured to `POST /press` with their own `page/row/col`.
- For PDQ features: a PDQ Deploy **Enterprise** license, PDQ installed on **this** machine (the CLI is local-only), the background service running, and the server started **elevated (as admin)**.

## Running

```bash
pip install -r requirements.txt   # fastapi, uvicorn
python main.py                    # serves on 0.0.0.0:7878
```

- `POST /press?page=&row=&col=` — called by every deck button on press.
- `POST /reload` — rebuild the menu tree from disk and redraw active pages (use after editing `menus/`).

All tunables — ports, PDQ paths, timeouts, colors, intervals, grid size — live in [`core/config.py`](core/config.py).

To have the server start automatically **elevated** at logon on the deployment machine, see [`deploy/`](deploy/) — a Task Scheduler installer (`install-autostart.bat`).

## Tests

```bash
pip install -r requirements-dev.txt   # adds pytest
python -m pytest                       # ~0.6s, no live Companion/PDQ needed
python -m pytest tests/test_pdq.py -q  # a single file
```

The suite covers the pure/near-pure layer — layout math, menu-tree resolution, PDQ argument building and DB reads, the OSC wire encoding, dispatcher press/nav, the dynamic menus, and the progress math — with Companion, the PDQ CLI/DB, ping, and scripts all faked.

## Project layout

```
main.py            FastAPI entrypoint (/press, /reload, background pollers)
core/
  config.py        all tunables
  dispatcher.py    press → action → redraw
  loader.py        build the menu tree from menus/
  layout.py        map a menu onto the 8×4 grid
  render.py        diff + draw (only changed cells)
  companion.py     visual facade over OSC
  osc.py           minimal OSC 1.0 sender (no dependency)
  runner.py        run button scripts by extension
  pdq.py           PDQ Deploy: DB reads + CLI deploys
  pcbrowser.py     the dynamic "PC" menu + shared catalog/ping cache
  pdqmenu.py       the batch "PDQ" deploy menu
  aoto.py          the "AOTO" LED-processor HTTP menu
  touch.py         the "Touch" TouchDesigner OSC menu
  ffs.py           the "Sync" FreeFileSync batch-job tab
  develop.py       the "Develop" git-pull + restart tab
  progress.py      the $(custom:Progress) refresh progress bar
  feedback.py      background poller for feedback buttons
  state.py         per-page navigation state
menus/             the menu hierarchy (folders = submenus, files = buttons)
aoto/              Aoto groups (groups/*.txt) and commands (commands.json)
touch/             Touch groups (groups/*.txt, "label = filename" per line)
pc_aliases.txt     optional "ip = alias" names for PDQ hosts on the deck
tests/             pytest suite
```

See [CLAUDE.md](CLAUDE.md) for the deeper architecture notes and conventions.

## License

See [LICENSE](LICENSE). The scripts under `NvidiaResAndColor/` drive NVIDIA display/EDID settings and require the NVIDIA WMI provider to be installed on the target machine; the NVIDIA WMI SDK itself is intentionally **not** redistributed here.
