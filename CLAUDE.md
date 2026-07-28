# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A modular menu system for a Stream Deck driven through [Bitfocus Companion](https://bitfocus.io/companion). The on-disk `menus/` folder tree defines a hierarchy of submenus and script-backed buttons; this FastAPI service renders that hierarchy onto the deck and runs the scripts when buttons are pressed.

## Commands

```bash
pip install -r requirements.txt   # fastapi, uvicorn, requests
python main.py                    # serves on 0.0.0.0:7878
```

- `POST /press?page=&row=&col=` — called by every deck button on press.
- `POST /reload` — rebuild the menu tree from disk and redraw active pages (use after editing `menus/`).

Companion must be running and reachable at `COMPANION_URL` (default `http://localhost:8000`, set in [core/config.py](core/config.py)).

## Key architectural constraint

Companion's HTTP API can only change a button's **visuals** (`/style`: text, colors), never its **action**. So dynamic submenus are impossible to build on Companion's side. Instead:

**Dumb deck, smart server.** Every button on the controlled page is configured in Companion to send the *same* generic `POST /press` with its own `page/row/col`. This server owns all state and logic, resolves what that coordinate means in the current menu, acts, and then re-pushes styles to **all 32 cells** to reflect the new view.

## Data flow (one press)

1. Deck button → `POST /press?page&row&col` ([main.py](main.py)).
2. [core/dispatcher.py](core/dispatcher.py) `handle_press` resolves current menu ([core/loader.py](core/loader.py) `resolve` walking [core/state.py](core/state.py) `path`), maps the cell via [core/layout.py](core/layout.py) `build_layout`, and acts:
   - **submenu** → push folder onto `state.path`, redraw;
   - **back / prev / next** → adjust nav state, redraw;
   - **command / feedback** → run the script ([core/runner.py](core/runner.py)) and write its result onto that one button.
3. Redraw = [core/render.py](core/render.py) `draw` via [core/companion.py](core/companion.py).

## Rendering performance

A naive redraw is 32 serial HTTP round-trips to Companion and is visibly slow. Four things keep it fast, in [core/render.py](core/render.py) / [core/companion.py](core/companion.py) / [core/osc.py](core/osc.py):

- **OSC for text** — the hot path (feedback updates) changes only text, sent over OSC/UDP (`/location/<p>/<r>/<c>/style/text`, port `OSC_PORT` 12321) — fire-and-forget, no round-trip. `render._emit` picks OSC when only text changed, HTTP when a color changed or on first draw.
- **Diffing** — `PageState.rendered` caches each cell's last `(text, bg, fg)`; only cells whose style changed are pushed. Single-button updates go through `render.update_cell` so the cache stays consistent.
- **Persistent `Session`** — one keep-alive connection for the HTTP (color) pushes.
- **Parallel pushes** — `companion.apply` fans HTTP updates out over a `ThreadPoolExecutor` (`RENDER_WORKERS`).

OSC has no built-in encoder dependency — [core/osc.py](core/osc.py) writes OSC 1.0 messages by hand. Colors still go over HTTP because Companion's OSC color format isn't relied upon here; only text is OSC. Knobs live in [core/config.py](core/config.py) (`OSC_HOST`/`OSC_PORT`, `CONNECT_TIMEOUT`, `READ_TIMEOUT`, `RENDER_WORKERS`). If you bypass `render`/`companion` to talk to Companion directly, update `PageState.rendered` too or the diff will skip real changes.

## Menu tree conventions (`menus/`)

The filesystem *is* the menu hierarchy. Naming (see [core/model.py](core/model.py) `make_label`):

- `NN_` prefix → ordering only; stripped from the display label.
- `01_lights/` (folder) → **submenu**.
- `01_on.py` (file) → **command button**; its first stdout line shows on press.
- `01_cpu.fb.py` (`.fb` before the extension) → **feedback button**; polled every `FEEDBACK_INTERVAL`s and on menu entry, stdout → button text.

Scripts run by extension ([core/runner.py](core/runner.py) `RUNNERS`): `.py .sh .ps1 .bat .cmd`, else executed directly. `cwd` is the script's own folder.

## Grid & layout

Fixed 8×4 (Stream Deck XL). Content fills rows 0–2 in reading order (24 slots/page); the bottom row (`NAV_ROW`) is reserved for **Back** (bottom-left) and **Prev/Next** paging (bottom-right), shown only when applicable. Change `GRID_ROWS`/`GRID_COLS`/`NAV_ROW` in [core/config.py](core/config.py) for other deck sizes.

## State & concurrency

Per-Companion-page state lives in [core/state.py](core/state.py) (`path`, `page_index`, cached `feedback_values`), guarded by a single `RLock` shared between the FastAPI request thread and the background feedback poller ([core/feedback.py](core/feedback.py), a daemon thread started in `main.lifespan`). Companion calls fail soft — a network error is logged and rendering continues.

## Files

- `*.companionconfig` — binary (encrypted) Companion deck export, imported through the Companion UI, not edited here. It's what configures the buttons to call `/press`.
