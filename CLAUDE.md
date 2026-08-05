# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working style (read first)

**Do only what was asked. Don't add unrequested features, variants, or "nice to have" extras.** If something beyond the request seems useful (extra buttons, presets, options, refactors), *ask first* whether it's wanted rather than building it. Scope creep — however well-intentioned — is not welcome here; a smaller change that does exactly what was asked is always preferred.

## What this is

A modular menu system for a Stream Deck driven through [Bitfocus Companion](https://bitfocus.io/companion). The on-disk `menus/` folder tree defines a hierarchy of submenus and script-backed buttons; this FastAPI service renders that hierarchy onto the deck and runs the scripts when buttons are pressed.

## Commands

```bash
pip install -r requirements.txt   # fastapi, uvicorn
python main.py                    # serves on 0.0.0.0:7878

pip install -r requirements-dev.txt   # adds pytest
python -m pytest                       # run tests (tests/, ~0.3s, no live Companion/PDQ)
python -m pytest tests/test_pdq.py -q  # a single file
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

Split across two channels ([core/pdq.py](core/pdq.py)), because PDQ Deploy 20.x separates them:

- **Reads** (package / target-list names) come from PDQ's **SQLite database** (`PDQ_DB_PATH`) — the CLI has no command to enumerate packages or target lists. `_connect` copies `Database.db` + `-wal` + `-shm` to a temp dir and reads the copy: reading the live WAL DB read-only silently misses data still in the `-wal` (Windows read-only-WAL limitation), and the copy also avoids locking the running DB.
- **Deploys** go through `PDQDeploy.exe` (`PDQ_DEPLOY_EXE`).

A `.pdq` button is a JSON config (`note` keys ignored), resolved by `args_from_config`:

- `{"package":"Install","targets":["PC1","PC2"]}` → `Deploy -Package -Targets` (specific PCs).
- `{"package":"Install","target_list":"All"}` → members read from the DB and **expanded into `-Targets`**. This is how we hit a Target List — the CLI has no `-TargetList` option, so we don't rely on Schedules.
- `{"schedule":12}` → `StartSchedule 12` (only if you keep Schedules in PDQ).

`runner.run_script` routes `.pdq` to `pdq.run_config` (uses `PDQ_TIMEOUT`); the deployment output shows on the button. Discovery: `python -m core.pdq packages | lists | members "<list>"`.

**Requirements**: Enterprise license, PDQ installed on **this** machine (CLI is local-only), background service running, and `main.py` started **elevated (as admin)** or `Deploy` fails with permission denied. Note the install path is `Program Files (x86)`.

## Dynamic menus (providers) and the PC browser

Menus can be generated at runtime, not just from folders. Two node types in [core/model.py](core/model.py) beyond the file-backed `CommandNode`:

- **`MenuNode.provider`** — a callable `provider(node) -> [child nodes]`. `children_of(node)` returns the provider's output if set, else static `children`. `loader.resolve` and `layout.build_layout` both go through `children_of`, so dynamic branches materialize lazily as you navigate. `context` carries data down a branch (e.g. which PC); `color_fn` gives a button a runtime color.
- **`ActionNode`** — a button that runs a Python callable (`on_press`) instead of a file. `after` decides what follows: `'text'` (show the returned string on the button), `'rerender'`, or `'back'` (pop up a level, e.g. after picking from a list).

In the dispatcher, `MenuNode` presses drill in; everything else routes by node type — `ActionNode` → `_run_action`, `CommandNode` → `_run_command`. `Slot.color` (from a node's `color_fn`) overrides the kind color in `render`.

Two dynamic features so far, both built on the same PDQ catalog:

[core/pcbrowser.py](core/pcbrowser.py) — a "ПК" button on the main menu (`attach` inserts it). Inside: a "change list" picker submenu (the shared `list_picker`), then one button per host in the **active PDQ target list** (default: first list), each colored by ping. Selecting a host opens a package menu; pressing a package deploys it to **that single host**. This module **owns the catalog + selection state** (active list, lists, packages, members, ping, aliases), cached so providers never hit the DB per render; refresh on start/reload. An optional **aliases file** (`PC_ALIASES_FILE`, lines `ip = alias`) is loaded in `refresh_catalog`; `host_label(host)` shows the alias above the ip and `members()` sorts by `_host_sort_key` (aliased hosts first, by alias, then the rest by host). Both the "ПК" menu and pdqmenu's "Выбор ПК" render hosts through `host_label`. A background ping sweep ([core/pcbrowser.py](core/pcbrowser.py) `start`, every `PING_INTERVAL`) updates status and calls `dispatcher.render_all_pages` — the render diff means only recolored buttons are pushed. `_ping_host` requires an actual reply (`TTL=` in output), since Windows `ping` returns 0 even when unreachable.

[core/pdqmenu.py](core/pdqmenu.py) — a "PDQ" button (inserted right after "ПК") for **batch** deploys to the active list. Inside: **Лист** (reuses `pcbrowser.list_picker`), **Выбор ПК** (toggle each host in/out with `on_press` → `toggle_host`, `after='rerender'`; ✓/✗ marker, ping color, dim `PC_OFF` when off), **Область** (an `ActionNode` toggling `_scope_active` between the whole list and enabled-only), then one button per package that deploys to `targets()` in a single `pdq.run`. It reads the catalog from `pcbrowser` and owns only the per-list `_disabled` set (absent host ⇒ enabled, so all-on by default) and the scope flag; no DB access, no background thread.

[core/aoto.py](core/aoto.py) — an "AOTO" button (after ПК/PDQ) for HTTP control of Aoto LED processors, grouped. **Groups are files** in `aoto/groups/*.txt` (one controller `host:port` per line, `#` comments, `NN_` filename prefix for ordering); **commands** are shared across groups in `aoto/commands.json`. AOTO → group list → per-group command menu. A command press fires an HTTP request (stdlib `urllib`) to **every** controller in the group in parallel and shows an aggregated summary (`OK n/n`, else `ERR k/n`). A command with a `response_field` is a **status** button: that dotted field (e.g. `obj.brightness`, `obj.hdrSetting`) is read from each controller's JSON reply. An optional `labels` map (`{"0":"from input","1":"SDR",…}`) turns raw values into names (`_map`). The group is aggregated by `_format_values` (all equal → the value; numbers differ → a `min-max` range; else a `/`-joined distinct list) with a `(k/n)` suffix on partial failure. The `_status` cache holds **per-controller** results `[(addr, ok, value), …]`, refreshed by a background poller (`start`, every `AOTO_POLL_INTERVAL`, calls `dispatcher.render_all_pages`) and re-polled on press. When the group **agrees**, the status button is a re-poll `ActionNode` (`after='rerender'`); when it **disagrees** (`_values_differ`), the same slot becomes a `MenuNode` that drills into `_status_detail` — one button per controller showing its IP's last octet and value (e.g. `.216 / HLG`). Status buttons/details are `Kind.COMMAND` with a green `color_fn` — deliberately **not** `Kind.FEEDBACK`, so the file-based feedback poller (which does `run_script(node.path)`) never touches these pathless nodes. Catalog + cache live here; providers only read them, HTTP happens on press or in the poller. Config/paths in [core/config.py](core/config.py) (`AOTO_*`).

**Brightness submenu.** Each AOTO group also gets a **«Управление яркостью»** submenu (`_brightness_children`), appended by `_group_commands` **only when the status command named `AOTO_BRIGHTNESS_STATUS_LABEL` (default `Яркость`) exists** — that same command both reads the current value and gates the menu. Inside: the current brightness (re-poll `ActionNode`, green), **Темнее / Ярче**, and step controls **Шаг ÷2 / Шаг N / Шаг ×2**. Темнее/Ярче are **per-controller**: `_adjust_brightness` reads each controller's brightness via the status command, shifts by the step, clamps to `[AOTO_BRIGHTNESS_MIN, brightness_limit(group)]`, and writes it back via `AOTO_SET_BRIGHTNESS_PATH` (body `{AOTO_SET_BRIGHTNESS_KEY: value}`), then re-polls so the shown value is truthful. The step is **AOTO-wide** module state (`_step`, `get_step`/`_scale_step`, floored at 1); the ceiling is **per-group** (`AOTO_BRIGHTNESS_LIMITS`, default `AOTO_BRIGHTNESS_LIMIT_DEFAULT` = 1500). All `Kind.COMMAND` + `After.RERENDER`; config in `AOTO_BRIGHTNESS_*` / `AOTO_SET_BRIGHTNESS_*`.

**Dynamic Range submenu.** Each AOTO group also gets a **«Dynamic Range»** submenu (`_hdr_children`), appended by `_group_commands` **only when the status command named `AOTO_HDR_STATUS_LABEL` (default `HDR`) exists** (gate only — like the brightness gate; the HDR reader isn't read here). Inside: one plain setter button per mode in `AOTO_HDR_MODES` (default `SDR`/`HLG`/`PQ`). Pressing one fires `run_group` with `_set_hdr_cmd(value)` — `POST AOTO_SET_HDR_PATH`, body `{AOTO_SET_HDR_KEY: value, **AOTO_SET_HDR_EXTRA}` (the varied `hdrSetting` plus the fixed `maximumBrightness`/`coefficient`) — to every controller, and shows the `OK n/n` summary (`Kind.COMMAND` + `After.TEXT`). **Note:** the `setHDR` *write* values (SDR=2/HLG=3/PQ=4) deliberately differ from the `getGlobalSettings` *read* scale in commands.json (SDR=1/HLG=2/PQ=3); this submenu only writes, so it shows no status. Config in `AOTO_HDR_*` / `AOTO_SET_HDR_*`.

[core/touch.py](core/touch.py) — a "Touch" button (after ПК/PDQ/AOTO) for firing OSC file triggers at **TouchDesigner**. **Groups are files** in `touch/groups/*.txt` (one `label = filename` per line, `#` comments, `NN_` filename prefix for ordering). Touch → group list → per-group buttons. Pressing a button sends **one** fire-and-forget OSC message to `TOUCH_OSC_HOST:TOUCH_OSC_PORT` (default `127.0.0.1:7777`) with the button's filename as a string argument, and shows `OK`. **Each group has its own OSC address** so different groups (стена, потолок, …) target different things: a group file sets it with an `@address = /path` directive line (parsed in `_parse_group`), falling back to `TOUCH_OSC_ADDRESS` (default `/file`) when absent. A group is a small `_Group` dataclass (`address` + `buttons`); `_group_buttons` captures the group's address into each button's `on_press`. The Touch tab also has **top-level buttons** (`TOUCH_COMMANDS`, default `file`/`base`/`fps`) alongside the groups: each fires a **no-argument** OSC message to an address named after it (`file` → `/file`), via `send_command`. The OSC goes out via `osc.send_to` (a generic sender added alongside `osc.send`, reusing the same wire encoding but to an arbitrary host/port — this is a **non-Companion** OSC target, so the `render`/`companion` diff cache doesn't apply). Catalog read from disk on start/reload; no background poller (no status to read). Config/paths in [core/config.py](core/config.py) (`TOUCH_*`).

[core/ffs.py](core/ffs.py) — a "Sync" tab for running **FreeFileSync** batch jobs. Jobs are configured in [core/config.py](core/config.py) as `FFS_JOBS = [(label, path-to-.ffs_batch), …]` — one button each. Pressing runs `FFS_EXE <batch>` (`subprocess.run`, `FFS_TIMEOUT`) and shows `OK` (exit 0) or `ERR …` (non-zero exit / missing exe / timeout) on the button. **Stateless** — reads `FFS_JOBS` from config, so no disk catalog, no poller, nothing to refresh; the subprocess runs outside `state.lock` (dispatcher runs `on_press` after releasing it). Fail-soft at the exe edge (`# noqa: BLE001`).

[core/develop.py](core/develop.py) — a "Develop" tab (appended last on the main menu) with a single **Pull & Restart** button. Pressing runs `git pull` in `PROJECT_ROOT` and, on success, restarts the process via `os.execv(sys.executable, [sys.executable, *sys.argv])` so new code takes effect. The pull result (`Pulled` / `Up to date`, or `ERR …`) is shown on the button first; the restart is scheduled `RESTART_DELAY` seconds later (a `threading.Timer` in `_schedule_restart`) so the deck renders that text before the process is replaced. A failed pull shows `ERR` and does **not** restart. Fail-soft at the git edge (`# noqa: BLE001`); no catalog, no poller, nothing to refresh. Config in [core/config.py](core/config.py) (`PROJECT_ROOT`, `GIT_PULL_TIMEOUT`, `RESTART_DELAY`).

**Active-state coloring.** An action command may declare `active_status` (the label of a status command) + `active_value`; its button then goes green (`_active_color`) when the group's agreed value for that status equals `active_value` — e.g. the Вход/Блэкаут/Фриз buttons highlight whichever screen type is currently active. Such buttons press via `_apply_tracked` (apply, then re-poll the referenced status so the highlight is truthful) with `after='rerender'`. A status command marked `"hidden": true` is polled for state but **not rendered** as a button — the way to track a value only for coloring, without adding a visible status button.

## Grid & layout

Fixed 8×4 (Stream Deck XL). Content fills rows 0–2 in reading order (24 slots/page); the bottom row (`NAV_ROW`) is reserved for **Back** and **Home** (bottom-left, cols 0/1) and **Prev/Next** paging (bottom-right), shown only when applicable. Back and Home appear together whenever `depth > 0`: **Back** pops one level (`Kind.BACK`), **Home** clears the path to the root menu (`Kind.HOME`, dispatched like an "enter" so root feedback refreshes). Change `GRID_ROWS`/`GRID_COLS`/`NAV_ROW` in [core/config.py](core/config.py) for other deck sizes.

## State & concurrency

Per-Companion-page state lives in [core/state.py](core/state.py) (`path`, `page_index`, cached `feedback_values`), guarded by a single `RLock` shared between the FastAPI request thread and the background feedback poller ([core/feedback.py](core/feedback.py), a daemon thread started in `main.lifespan`). OSC sends fail soft — a socket error is logged and rendering continues.

## Progress countdown (custom variable)

[core/progress.py](core/progress.py) keeps a Companion **custom variable** `$(custom:Progress)` updated with a **0..100** progress value toward the next feedback refresh (0 right after a refresh, filling to 100 as the next approaches — a progress-bar percentage, `percent()`), so a button on an auto-updating page can show a bar. A daemon thread (`start`, started in `main.lifespan`) publishes once per `PROGRESS_TICK` via `companion.set_custom_variable`; the feedback poller's `on_cycle=progress.mark` resets `_next_due` at the end of each cycle so the value stays synced to the real cadence instead of free-running. Custom variables are **global** (not per-page), so the value is the same everywhere — the "only on auto-updating pages" part is just where you place `$(custom:Progress)`. This is the one Companion write that legitimately bypasses the `render` cell diff (it's not a button), so it goes straight through `companion`/`osc`. Names/tick live in [core/config.py](core/config.py) (`PROGRESS_VAR`, `PROGRESS_TICK`).

## Conventions (keep these — they're why the code stays small)

These are the principles the codebase already follows. Match them when extending it:

1. **One module, one job.** Each `core/` file does exactly one thing (`osc` = wire format, `companion` = visual facade, `render` = diff+draw, `layout` = grid math, `loader` = tree from disk, `dispatcher` = press→action, `pdq` = PDQ, `pcbrowser` = the PC feature + shared catalog, `pdqmenu` = the batch-deploy menu, `aoto` = the LED-processor HTTP menu, `touch` = the TouchDesigner OSC menu, `ffs` = the FreeFileSync "Sync" tab, `develop` = the pull+restart tab, `progress` = the refresh progress bar). A new feature gets its own module rather than swelling an existing one (e.g. `pdqmenu` reuses `pcbrowser`'s catalog through its public API instead of duplicating it or bloating it).
2. **Only `render`/`companion` talk to Companion.** Every button update goes through `render.draw`/`render.update_cell` so the `PageState.rendered` diff cache stays truthful. Never call `osc`/`companion` directly from a feature — you'll desync the diff and push stale or duplicate updates.
3. **Config over constants-in-code.** Every tunable (ports, paths, timeouts, colors, intervals, grid size) lives in [core/config.py](core/config.py). Don't hardcode at the call site. Slot kinds and `ActionNode.after` values are named in [core/constants.py](core/constants.py) (`Kind`, `After`) — use those, never bare `"menu"`/`"back"` string literals.
4. **Fail soft at every external edge.** OSC, the PDQ CLI, the PDQ DB, ping, and user scripts must never crash the deck. Catch, log a warning, and surface the problem as button text (`ERR`) — the deck keeps working. The broad `except Exception` blocks are deliberate for this reason (marked `# noqa: BLE001`), and are only allowed at those I/O edges, not in core logic.
5. **Providers must be cheap.** A `provider`/`color_fn` runs on every render and press. Never do I/O (DB, network, subprocess) inside one — read from a module-level cache that a background thread or an explicit refresh populates (see `pcbrowser`'s catalog/ping caches).
6. **Hold the lock briefly; block outside it.** `state.lock` guards navigation state only. Long work (running a script, a PDQ deploy, OSC/DB I/O) happens *after* the `with state.lock` block so presses on other pages aren't stalled.
7. **Nodes are dataclasses; logic is small pure functions.** Prefer `from __future__ import annotations`, type hints, and functions that take data and return data (e.g. `pdq.deploy_args`, `layout.build_layout`) so behaviour is testable without a running deck.
8. **Verify the changed path before finishing.** No test suite yet (see below), so at minimum `python -c "import main"` and exercise the touched flow with `osc.send`/`pdq.run` monkeypatched — the pattern used throughout this project's development.

## Known gaps / tech debt

Recorded so it isn't rediscovered each session. Roughly prioritized:

- **Test coverage is broad but not total.** `tests/` (pytest, 147 tests) covers the pure/near-pure layer — `make_label`, `children_of`, `build_layout` (kinds/nav/pagination/color), `pdq.deploy_args`/`args_from_config`/`run_config`, `render` transport selection, dispatcher press/nav (with `companion`/`run_script` monkeypatched), the OSC wire encoding in `osc` (strings/tags/padding/sender + the custom-variable address, socket monkeypatched), the DB reads in `pdq` (real SQLite fixture built per test, incl. the WAL-snapshot path), `pcbrowser` catalog/active-list/ping-color/alias-label-and-sort/provider tree (with the `pdq` DB layer faked), `pdqmenu` enable-disable/scope state + PDQ menu tree (with the `pcbrowser` catalog faked), `aoto` group/command loading + HTTP aggregation + label mapping + differ-drilldown + active-state coloring menu tree + the brightness submenu (per-group limit, step ×2/÷2 floor, per-controller read-shift-clamp-write, submenu gating/layout) + the Dynamic Range submenu (gating, mode-setter layout, per-controller setHDR body) (with `aoto._request` faked and tmp catalog files), `touch` group loading + per-group `@address` + OSC file trigger + no-arg top-level commands + group/button menu tree (with `osc.send_to` faked and tmp group files), `ffs` job-button menu + batch run (with `subprocess.run` faked: OK/error/missing-exe + argv), `develop` pull-and-restart (with `_git_pull`/`_schedule_restart` faked so no subprocess runs and the process is never replaced), and `progress` 0..100 fill math + custom-variable publish (with a fake monotonic clock). Tests take a synthetic tree via `monkeypatch.setattr(dispatcher, "_tree", ...)`, point `pdq.PDQ_DB_PATH` at a tmp DB, and clear `state._states`. Still uncovered: the background pollers (feedback loop, ping sweep, aoto status poller, progress ticker) as running threads, and `runner.run_script` subprocess execution.
- **PDQ DB reads copy the whole file each call.** `pdq._connect` snapshots `Database.db`(+wal/shm) per call, so `refresh_catalog` does ~3 copies. Fine at start/reload frequency; batch into one snapshot if it ever gets hot.
- **Ping sweep redraws every page.** `render_all_pages` rebuilds layout for all pages every `PING_INTERVAL` even if none is on the PC subtree. Cheap (the diff pushes nothing when unchanged) but wasteful; could skip pages with no `color_fn` nodes.
- **Aoto status poller polls every group.** `aoto._poll_statuses` queries the status commands of *all* groups each `AOTO_POLL_INTERVAL`, not just the group currently on screen (it doesn't track which group is in view). Fine at a handful of groups/controllers; if it grows, scope the poll to the visible group (mirrors the ping-sweep gap above).

## Files

- `*.companionconfig` — binary (encrypted) Companion deck export, imported through the Companion UI, not edited here. It's what configures the buttons to call `/press`.
