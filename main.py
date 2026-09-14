"""FastAPI entrypoint for the Companion menu system.

Every deck button is configured in Companion to POST its own location here on
press. This server owns the menu state and redraws the deck via Companion's
HTTP API. See CLAUDE.md and core/ for the architecture.

It also serves a READ-ONLY status page (GET / for the page, GET /status for its
JSON) showing the live state of the parameters the deck can turn; see
core/webstatus.py. A TouchDesigner client pushes its deck buttons here
(POST /touch/buttons + /touch/ping); see core/touch.py.
"""
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from core import (
    aoto, aotopresets, config, dispatcher, feedback, osc_buttons, pcbrowser, pixelhue, progress, state, touch,
    webstatus,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load PDQ package/target-list names, draw every deck's page, then start the
    # feedback poller and the PC ping sweep (which redraws pages as hosts change).
    pcbrowser.refresh_catalog()
    aoto.refresh()
    aotopresets.refresh()
    osc_buttons.refresh()
    for page in config.DECK_PAGES:      # one page per deck, so none is blank at boot
        dispatcher.render_page(page)
        dispatcher.refresh_feedback(page)
    feedback.start_poller(
        dispatcher.refresh_feedback, state.all_pages, config.FEEDBACK_INTERVAL,
        on_cycle=progress.mark,  # reset the $(custom:Progress) countdown each cycle
    )
    pcbrowser.start(dispatcher.render_all_pages)
    aoto.start(dispatcher.render_all_pages)    # poll Aoto status commands
    pixelhue.start(dispatcher.render_all_pages)  # poll PixelHue node/screens/presets
    progress.start(config.FEEDBACK_INTERVAL)  # tick the countdown once a second
    webstatus.start()  # refresh the status page's data while a browser has it open
    touch.start(dispatcher.render_all_pages)  # drop dead Touch clients (redraws)
    yield


app = FastAPI(title="CompanionHelper", lifespan=lifespan)


@app.post("/press")
def handle_button_press(page: str, row: int, col: int):
    log.info("[PRESS] page=%s row=%s col=%s", page, row, col)
    dispatcher.handle_press(page, row, col)
    return {"status": "ok", "received": {"page": page, "row": row, "col": col}}


@app.post("/reload")
def reload_menus():
    """Rebuild the menu tree from disk and redraw every active page."""
    dispatcher.reload_tree()
    dispatcher.render_all_pages()
    return {"status": "reloaded"}


@app.post("/touch/buttons")
def touch_buttons(payload: dict):
    """A TouchDesigner client registers/refreshes its deck buttons and press target."""
    try:
        return touch.set_buttons(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@app.post("/touch/ping")
def touch_ping(payload: dict):
    """A TouchDesigner client heartbeat: keeps its buttons on the deck."""
    try:
        return touch.ping(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@app.get("/", response_class=HTMLResponse)
def status_page():
    """The read-only status page (web/index.html, re-read on every request)."""
    return HTMLResponse(webstatus.page_html())


@app.get("/status")
def status_data():
    """The page's JSON snapshot. Answers instantly -- the reads happen in the background."""
    return webstatus.snapshot()


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT)

