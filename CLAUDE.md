# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A modular menu system for a Stream Deck driven through [Bitfocus Companion](https://bitfocus.io/companion). The on-disk `menus/` folder tree defines a hierarchy of submenus and script-backed buttons; this FastAPI service renders that hierarchy onto the deck and runs the scripts when buttons are pressed.

## Commands

```bash
pip install -r requirements.txt   # fastapi, uvicorn
python main.py                    # serves on 0.0.0.0:7878
```

- `POST /press?page=&row=&col=` — called by every deck button on press (Companion → here, HTTP).
- `POST /reload` — rebuild the menu tree from disk and redraw active pages (use after editing `menus/`).

Two transports, opposite directions: **presses come in over HTTP** (FastAPI), **button visuals go out over OSC/UDP** to Companion's OSC listener (`OSC_HOST`/`OSC_PORT` 12321 in [core/config.py](core/config.py)). Companion must have OSC control enabled.

## Key architectural constraint

Companion's remote API can only change a button's **visuals** (text, colors), never its **action**. So dynamic submenus are impossible to build on Companion's side. Instead:

**Dumb deck, smart server.** Every button on the controlled page is configured in Companion to send the *same* generic `POST /press` with its own `page/row/col`. This server owns all state and logic, resolves what that coordinate means in the current menu, acts, and then re-pushes styles to **all 32 cells** to reflect the new view.

## Data flow (one press)

1. Deck button → `POST /press?page&row&col` ([main.py](main.py)).
2. [core/dispatcher.py](core/dispatcher.py) `handle_press` resolves current menu ([core/loader.py](core/loader.py) `resolve` walking [core/state.py](core/state.py) `path`), maps the cell via [core/layout.py](core/layout.py) `build_layout`, and acts:
   - **submenu** → push folder onto `state.path`, redraw;
   - **back / prev / next** → adjust nav state, redraw;
   - **command / feedback** → run the script ([core/runner.py](core/runner.py)) and write its result onto that one button.
3. Redraw = [core/render.py](core/render.py) `draw` via [core/companion.py](core/companion.py).

## Rendering performance

A naive redraw would be dozens of HTTP round-trips and is visibly slow. Two things keep it fast, in [core/render.py](core/render.py) / [core/companion.py](core/companion.py) / [core/osc.py](core/osc.py):

- **OSC/UDP for everything** — text (`/location/<p>/<r>/<c>/style/text <text>`) and colors (`/style/bgcolor` and `/style/color` as `r g b` 0-255) are sent fire-and-forget, no round-trip. A text-only change is one message; a color change is three (`companion.set_style`). Colors are stored as `#rrggbb` and converted to r/g/b in `companion._rgb`.
- **Diffing** — `PageState.rendered` caches each cell's last `(text, bg, fg)`; `render._emit` pushes only cells whose style changed, and prefers `set_text` (1 msg) over `set_style` (3 msgs) when only text differs. A feedback poll touches ~1–2 cells, not 32. Single-button updates go through `render.update_cell` so the cache stays consistent.

[core/osc.py](core/osc.py) writes OSC 1.0 messages by hand (no dependency). Knobs live in [core/config.py](core/config.py) (`OSC_HOST`/`OSC_PORT`). If you bypass `render`/`companion` to talk to Companion directly, update `PageState.rendered` too or the diff will skip real changes.

## Menu tree conventions (`menus/`)

The filesystem *is* the menu hierarchy. Naming (see [core/model.py](core/model.py) `make_label`):

- `NN_` prefix → ordering only; stripped from the display label.
- `01_lights/` (folder) → **submenu**.
- `01_on.py` (file) → **command button**; its first stdout line shows on press.
- `01_cpu.fb.py` (`.fb` before the extension) → **feedback button**; polled every `FEEDBACK_INTERVAL`s and on menu entry, stdout → button text.
- `01_install.pdq` → **PDQ Deploy button**; a JSON config, not an executable (see below).

Scripts run by extension ([core/runner.py](core/runner.py) `RUNNERS`): `.py .sh .ps1 .bat .cmd`, else executed directly. `cwd` is the script's own folder. `run_script` special-cases `.pdq` before the generic path.

## PDQ Deploy integration

A `.pdq` button is a JSON config describing a PDQ Deploy action, run via [core/pdq.py](core/pdq.py) (which shells out to `PDQDeploy.exe`, `PDQ_DEPLOY_EXE` in config):

- `{"package": "7-Zip", "targets": ["PC1","PC2"]}` → `Deploy -Package -Targets` (specific PCs).
- `{"schedule": 12}` → `StartSchedule 12` — the only way to hit a **Target List** (pre-make a Schedule in PDQ that points at the list; the CLI can't enumerate or deploy to Target Lists directly). A `note` key is ignored.

`runner.run_script` routes `.pdq` to `pdq.run_config` (uses `PDQ_TIMEOUT`, not the command timeout); the deployment id / output shows on the button. Discovery helpers to fill in configs: `python -m core.pdq packages` and `python -m core.pdq schedules`.

**Requirements** (all real constraints of the PDQ CLI): Enterprise license, PDQ Deploy installed on **this** machine (CLI is local-only), the PDQ background service running, and `main.py` started **elevated (as admin)** — otherwise `Deploy`/`StartSchedule` fail. `GetPackageNames` is the only Free-tier command.

## Grid & layout

Fixed 8×4 (Stream Deck XL). Content fills rows 0–2 in reading order (24 slots/page); the bottom row (`NAV_ROW`) is reserved for **Back** (bottom-left) and **Prev/Next** paging (bottom-right), shown only when applicable. Change `GRID_ROWS`/`GRID_COLS`/`NAV_ROW` in [core/config.py](core/config.py) for other deck sizes.

## State & concurrency

Per-Companion-page state lives in [core/state.py](core/state.py) (`path`, `page_index`, cached `feedback_values`), guarded by a single `RLock` shared between the FastAPI request thread and the background feedback poller ([core/feedback.py](core/feedback.py), a daemon thread started in `main.lifespan`). OSC sends fail soft — a socket error is logged and rendering continues.

## Files

- `*.companionconfig` — binary (encrypted) Companion deck export, imported through the Companion UI, not edited here. It's what configures the buttons to call `/press`.
