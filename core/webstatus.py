"""Read-only web status page: the live state of every knob the deck can turn.

`GET /` serves one small self-contained HTML page (web/index.html) that polls
`GET /status` once a second and paints what the deck knows: the Aoto parameters
of every group, the PixelHue node/flags/screens, and the ping status of the
active PDQ target list. Nothing here writes anything -- no device command, no
deck render.

Freshness. `GET /status` never touches the network: it hands out the last
snapshot instantly, so a browser can never be left waiting on a slow
controller. A background thread re-reads the devices every
WEB_REFRESH_INTERVAL seconds and rebuilds that snapshot, but ONLY while a page
is watching (any /status request within WEB_IDLE_TIMEOUT) -- a closed tab costs
nothing, and several open tabs do not multiply the device load (they share the
one snapshot). Every snapshot carries its age, which the page shows.

Aoto reads are grouped by ENDPOINT: the dozen parameters of a group all live in
the same getGlobalSettings reply, so a refresh sends ONE request per controller
per endpoint rather than one per parameter (aoto.probe_raw + aoto.field_value).

Which parameters exist is data, not code: the deck's status commands come from
aoto/commands.json, the rest from the capture catalog
aoto/presets/parameters.json -- adding a parameter to either adds it to the
page. Parameters that read the same thing are shown once (deck labels win), and
the aggregated value is formatted by aoto.status_text, so the page and the deck
never disagree about how a value is shown.
"""
from __future__ import annotations

import html
import json
import logging
import threading
import time

from . import aoto, aotopresets, diag, pcbrowser, pixelhue
from .config import (
    AOTO_BRIGHTNESS_STATUS_LABEL,
    PORT,
    WEB_IDLE_TIMEOUT,
    WEB_LOGS_PAGE,
    WEB_PAGE,
    WEB_REFRESH_INTERVAL,
)

log = logging.getLogger("webstatus")

_lock = threading.RLock()
_snapshot: dict = {}            # the last built snapshot (served as-is)
_read_at: float | None = None   # monotonic time of the last completed read
_viewer_until: float = 0.0      # reads keep running while a page asked recently
_wake = threading.Event()       # set when a page lands on stale data (refresh now)


# --- read plan: which parameters are shown, and how to read them ------------
def _body_key(body) -> str:
    """Request identity of a body: 'no body' and 'empty body' are the same call."""
    return json.dumps(body, sort_keys=True, default=str) if body else "{}"


def _read_key(spec: dict) -> tuple:
    """Identity of a READ: two parameters reading the same thing are shown once."""
    r = spec["read"]
    return (r["method"], r["path"], _body_key(r.get("body")), r["field"])


def _endpoint_key(spec: dict) -> tuple:
    """Identity of a REQUEST: parameters sharing it come from one reply."""
    r = spec["read"]
    return (r["method"], r["path"], _body_key(r.get("body")))


def _status_specs() -> list[dict]:
    """The deck's status commands (commands.json) as read specs, in file order."""
    out: list[dict] = []
    for cmd in aoto.commands():
        field = cmd.get("response_field")
        if not field or not cmd.get("path"):
            continue
        out.append({
            "label": cmd.get("label") or field,
            "labels": cmd.get("labels"),
            "read": {"method": (cmd.get("method") or "POST").upper(),
                     "path": cmd.get("path"), "body": cmd.get("body"), "field": field},
        })
    return out


def _catalog_specs() -> list[dict]:
    """The capture catalog (aoto/presets/parameters.json) as read specs."""
    out: list[dict] = []
    for p in aotopresets.parameters():
        g = p.get("get") or {}
        field, path = g.get("field"), g.get("path")
        if not (isinstance(field, str) and field and isinstance(path, str) and path):
            continue
        out.append({
            "label": p.get("name") or field,
            "labels": None,
            "read": {"method": (g.get("method") or "POST").upper(), "path": path,
                     "body": g.get("body"), "field": field},
        })
    return out


def read_specs() -> list[dict]:
    """Every parameter the page shows: deck statuses first, then catalog extras.

    A catalog row that reads exactly what a status command already reads is
    dropped, so `Яркость` / `HDR` / `Тест` are not listed twice."""
    specs: list[dict] = []
    seen: set[tuple] = set()
    for spec in _status_specs() + _catalog_specs():
        key = _read_key(spec)
        if key in seen:
            continue
        seen.add(key)
        specs.append(spec)
    return specs


def _read_group(group: str, specs: list[dict]) -> dict[tuple[str, str], list]:
    """Read a group's parameters: ONE request per distinct endpoint."""
    by_endpoint: dict[tuple, list[dict]] = {}
    for spec in specs:
        by_endpoint.setdefault(_endpoint_key(spec), []).append(spec)

    out: dict[tuple[str, str], list] = {}
    for group_specs in by_endpoint.values():
        read = group_specs[0]["read"]
        replies = aoto.probe_raw(group, {"method": read["method"], "path": read["path"],
                                        "body": read.get("body")})
        for spec in group_specs:
            field = spec["read"]["field"]
            results = [
                (addr, ok, aoto.field_value(reply, field) if ok else None)
                for addr, ok, reply in replies
            ]
            out[(group, spec["label"])] = results
            _note_missing_field(group, spec, replies, results)
    return out


def _note_missing_field(group: str, spec: dict, replies: list, results: list) -> None:
    """Say why a parameter shows nothing when the device DID answer.

    Transport failures are already logged (with their URL) by aoto._send; this
    covers the other silent case: the reply simply has no such field."""
    target = f"{group}/{spec['label']}"
    if results and all(ok and value is not None for _a, ok, value in results):
        diag.resolved("aoto", target)
        return
    for _addr, ok, reply in replies:
        if ok:
            keys = ", ".join(list(reply)[:6]) if isinstance(reply, dict) else str(reply)[:40]
            diag.record("aoto", target,
                        f"в ответе нет поля {spec['read']['field']} (в ответе: {keys})")
            return


# --- formatting (pure: data in, JSON-able data out) -------------------------
def _cmd(spec: dict) -> dict:
    """The command dict aoto.status_text/values_differ expect (labels drive names)."""
    return {"response_field": spec["read"]["field"], "labels": spec["labels"]}


def _shown(value, labels):
    """A raw value through the parameter's label map (2 -> 'HLG'), if it has one."""
    if labels and value is not None:
        return labels.get(str(value), value)
    return value


def _state(spec: dict, results) -> str:
    """ok (all replied, one value) / mixed / partial / error / unknown (no data yet)."""
    if results is None:
        return "unknown"
    if not results:
        return "error"                      # a group with no controllers
    n_ok = sum(1 for _a, ok, _v in results if ok)
    if n_ok == 0:
        return "error"
    if n_ok < len(results):
        return "partial"
    return "mixed" if aoto.values_differ(_cmd(spec), results) else "ok"


def _controllers(spec: dict, results) -> list[dict]:
    """Per-controller values (the page lists them when the group disagrees/fails)."""
    return [
        {"addr": addr, "ok": ok, "value": _shown(value, spec["labels"])}
        for addr, ok, value in (results or [])
    ]


def _brightness_percent(group: str, values: list) -> str | None:
    """'80%' / '80-100%' of the group's ceiling (aoto '@max' / config), or None."""
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    limit = aoto.brightness_limit(group)
    if not nums or len(nums) != len(values) or limit <= 0:
        return None
    pcts = sorted(round(v / limit * 100) for v in nums)
    return f"{pcts[0]}%" if pcts[0] == pcts[-1] else f"{pcts[0]}-{pcts[-1]}%"


def _param(group: str, spec: dict, results) -> dict:
    if results is None:
        value = "…"                         # nothing read yet
    elif not results:
        value = "нет контроллеров"
    else:
        value = aoto.status_text(_cmd(spec), results)
    item = {"label": spec["label"], "state": _state(spec, results), "value": value,
            "controllers": _controllers(spec, results)}
    if spec["label"] == AOTO_BRIGHTNESS_STATUS_LABEL:      # nits + % of the ceiling
        pct = _brightness_percent(group, [v for _a, ok, v in (results or []) if ok])
        if pct:
            item["percent"] = pct
    return item


def _aoto_section(specs: list[dict], results: dict) -> list[dict]:
    return [
        {"group": group,
         "params": [_param(group, spec, results.get((group, spec["label"]))) for spec in specs]}
        for group in aoto.groups()
    ]


def _pc_section() -> dict:
    age = pcbrowser.ping_age()
    return {
        "active_list": pcbrowser.active_list(),
        "checked_ago": None if age is None else round(age, 1),
        "hosts": [
            {"host": host, "alias": pcbrowser.alias(host), "up": pcbrowser.status(host)}
            for host in pcbrowser.members()
        ],
    }


def _pixelhue_section() -> dict:
    node, err = pixelhue.node_state()
    node = node if isinstance(node, dict) else None
    online = node.get("online") if node else None
    return {
        "host": pixelhue.address(),
        "version": node.get("version") if node else None,
        "online": None if node is None else (1 if online in (1, "1", True) else 0),
        "error": err,
        "mapping": pixelhue.mapping_enabled(),
        "screens": [{"id": s.screen_id, "name": s.name, "freeze": s.freeze,
                     "ftb": s.ftb_enable} for s in pixelhue.screens()],
        "presets": len(pixelhue.presets()),
    }


# --- the snapshot ----------------------------------------------------------
def _pull_pixelhue() -> None:
    """Re-read the PixelHue device, fail-soft: an offline device is not an error."""
    try:
        pixelhue.refresh_now()
    except Exception as e:  # noqa: BLE001 - the page keeps showing the other sections
        log.warning("pixelhue pull for the status page failed: %s", e)
        diag.record("web", "обновление статуса", f"pixelhue: {e}"[:120])


def refresh() -> None:
    """Re-read the devices and rebuild the snapshot (background thread only).

    The PixelHue pull runs CONCURRENTLY with the Aoto reads: they are unrelated
    devices, and an unreachable one (four requests, each waiting for its
    timeout) must not delay the rest of the page."""
    global _snapshot, _read_at
    puller = threading.Thread(target=_pull_pixelhue, name="webstatus-pixelhue", daemon=True)
    puller.start()
    specs = read_specs()
    results: dict[tuple[str, str], list] = {}
    for group in aoto.groups():
        results.update(_read_group(group, specs))
    puller.join()
    snapshot = {
        "read_at": time.strftime("%H:%M:%S"),
        "aoto": _aoto_section(specs, results),
        "pc": _pc_section(),
        "pixelhue": _pixelhue_section(),
    }
    with _lock:
        _snapshot = snapshot
        _read_at = time.monotonic()


def snapshot() -> dict:
    """The page's data: the last snapshot plus its age. Never does I/O.

    Asking for it marks a page as watching -- that is what keeps the refresher
    thread reading the devices (see watched/start). Landing on stale data also
    wakes the refresher, so a page opened after a quiet spell fills in at once
    instead of waiting out the interval."""
    global _viewer_until
    now = time.monotonic()
    with _lock:
        _viewer_until = now + WEB_IDLE_TIMEOUT
        snap, at = _snapshot, _read_at
    age = None if at is None else round(now - at, 1)
    if age is None or age > WEB_REFRESH_INTERVAL:
        _wake.set()
    return {**snap, "age": age, "interval": WEB_REFRESH_INTERVAL,
            "problems": diag.problems(),
            "stale": age is None or age > WEB_REFRESH_INTERVAL * 2}


def log_entries() -> list[dict]:
    """The open problems, for the log window (GET /logs.json)."""
    return diag.entries()


def watched() -> bool:
    """True while a page has requested the snapshot within WEB_IDLE_TIMEOUT."""
    with _lock:
        return time.monotonic() < _viewer_until


def start() -> None:
    """Start the refresher: one read at boot, then only while a page is watching.

    A steady stream of requests does not speed the cadence up (the wait is a
    full interval); only stale data wakes it early."""

    def loop():
        first = True
        while True:
            if first or watched():
                first = False
                try:
                    refresh()
                except Exception as e:  # noqa: BLE001 - the page must never die
                    log.warning("web status refresh failed: %s", e)
                    diag.record("web", "обновление статуса", str(e)[:120])
            _wake.clear()
            _wake.wait(WEB_REFRESH_INTERVAL)

    threading.Thread(target=loop, name="webstatus", daemon=True).start()


# --- the page itself -------------------------------------------------------
_FALLBACK_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>CompanionHelper</title></head>
<body style="font:14px/1.6 system-ui;background:#101215;color:#dde1e6;padding:2rem">
<h1>Страница недоступна</h1>
<p>Не удалось прочитать {page}: {error}</p>
<p>Данные по-прежнему отдаются в <a style="color:#79c0ff" href="/status">/status</a>.</p>
</body></html>
"""


def page_html() -> str:
    """The page markup (config.WEB_PAGE), re-read per request so edits land live."""
    return _read_page(WEB_PAGE)


def logs_page_html() -> str:
    """The log window markup (config.WEB_LOGS_PAGE), also re-read per request."""
    return _read_page(WEB_LOGS_PAGE)


def _read_page(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - a missing page must not 500
        log.warning("web page unreadable (%s): %s", path, e)
        return _FALLBACK_PAGE.format(page=html.escape(str(path)), error=html.escape(str(e)))


def page_url() -> str:
    """The page's URL as a browser ON THIS MACHINE should open it (the Develop tab)."""
    return f"http://127.0.0.1:{PORT}/"
