"""FastAPI entrypoint for the Companion menu system.

Every deck button is configured in Companion to POST its own location here on
press. This server owns the menu state and redraws the deck via Companion's
HTTP API. See CLAUDE.md and core/ for the architecture.
"""
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from core import config, dispatcher, feedback, pcbrowser, progress, state

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load PDQ package/target-list names, draw the root menu, then start the
    # feedback poller and the PC ping sweep (which redraws pages as hosts change).
    pcbrowser.refresh_catalog()
    dispatcher.render_page(config.DEFAULT_PAGE)
    dispatcher.refresh_feedback(config.DEFAULT_PAGE)
    feedback.start_poller(
        dispatcher.refresh_feedback, state.all_pages, config.FEEDBACK_INTERVAL,
        on_cycle=progress.mark,  # reset the $(custom:Progress) countdown each cycle
    )
    pcbrowser.start(dispatcher.render_all_pages)
    progress.start(config.FEEDBACK_INTERVAL)  # tick the countdown once a second
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


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT)
