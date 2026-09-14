"""touch: the TouchDesigner client registry, the OSC press proxy, and the menu tree.

No HTTP and no network: clients are posted to set_buttons() directly, the OSC
send is monkeypatched so nothing leaves the machine, and the clock is a seam
(touch._now) so a client can be aged without sleeping.
"""
import pytest

from core import touch
from core.config import (
    COLORS,
    TOUCH_CLIENT_TIMEOUT,
    TOUCH_OSC_ADDRESS,
    TOUCH_OSC_HOST,
    TOUCH_OSC_PORT,
    TOUCH_SWEEP_INTERVAL,
)
from core.constants import After, Kind
from core.model import ActionNode, MenuNode


@pytest.fixture
def registry(monkeypatch):
    """An empty client registry, a frozen clock and a recorded OSC output."""
    monkeypatch.setattr(touch, "_clients", {})
    clock = {"now": 1000.0}
    monkeypatch.setattr(touch, "_now", lambda: clock["now"])
    sent = []
    monkeypatch.setattr(touch.osc, "send_to",
                        lambda host, port, address, *args: sent.append((host, port, address, args)))
    return {"clock": clock, "sent": sent}


def _post(client_id="wall", **extra):
    payload = {"client": client_id, "buttons": [{"id": "intro", "label": "Intro"}]}
    payload.update(extra)
    return touch.set_buttons(payload)


# --- registration ----------------------------------------------------------
def test_set_buttons_registers_a_client_with_defaults(registry):
    result = _post()
    assert result == {"status": "ok", "client": "wall", "buttons": 1}
    client = touch.get("wall")
    assert (client.host, client.port, client.address) == (TOUCH_OSC_HOST, TOUCH_OSC_PORT,
                                                          TOUCH_OSC_ADDRESS)
    assert client.label == "wall"                      # no label sent -> the id
    assert [(b.id, b.label, b.color, b.active) for b in client.buttons] == \
        [("intro", "Intro", None, False)]


def test_set_buttons_takes_the_clients_own_target_and_label(registry):
    _post(label="Стена", host="10.0.0.9", port=9000, address="/wall")
    client = touch.get("wall")
    assert (client.label, client.host, client.port, client.address) == \
        ("Стена", "10.0.0.9", 9000, "/wall")


def test_set_buttons_replaces_the_whole_list(registry):
    _post(buttons=[{"id": "a"}, {"id": "b"}, {"id": "c"}])
    _post(buttons=[{"id": "b", "label": "B"}])
    assert [b.id for b in touch.get("wall").buttons] == ["b"]
    assert touch.get("wall").buttons[0].label == "B"


def test_a_button_without_an_id_is_dropped(registry, caplog):
    _post(buttons=[{"label": "no id"}, {"id": "ok"}, "junk"])
    assert [b.id for b in touch.get("wall").buttons] == ["ok"]
    assert "without an id" in caplog.text


def test_bad_color_is_ignored_and_active_is_kept(registry, caplog):
    _post(buttons=[{"id": "a", "color": "red"}, {"id": "b", "color": "#F00"},
                   {"id": "c", "active": True}, {"id": "d", "active": "yes"}])
    buttons = {b.id: b for b in touch.get("wall").buttons}
    assert buttons["a"].color is None                  # not a hex -> dropped
    assert buttons["b"].color == "#f00"                # normalized to lower case
    assert buttons["c"].active is True
    assert buttons["d"].active is False                # only a real True counts
    assert "ignoring bad color" in caplog.text


def test_set_buttons_rejects_an_unusable_payload(registry):
    with pytest.raises(ValueError):
        touch.set_buttons({"buttons": []})             # no client id
    with pytest.raises(ValueError):
        touch.set_buttons({"client": "wall", "buttons": {"id": "a"}})   # not a list
    with pytest.raises(ValueError):
        touch.set_buttons({"client": "wall", "port": "not-a-port"})
    assert touch.clients() == []                       # nothing half-registered


def test_clients_are_ordered_by_label_ignoring_case(registry):
    _post("b", label="Яркость")
    _post("a", label="Атмосфера")
    _post("d", label="Deck")
    _post("e", label="alpha")
    _post("c")                                          # no label -> the id is the label
    labels = [c.label for c in touch.clients()]
    assert labels == sorted(labels, key=str.casefold)    # stable submenu order
    assert "c" in labels


# --- ping and dead clients -------------------------------------------------
def test_ping_keeps_a_registered_client_alive(registry):
    _post()
    registry["clock"]["now"] += TOUCH_CLIENT_TIMEOUT - 1
    assert touch.ping({"client": "wall"}) == {"status": "ok", "client": "wall", "buttons": 1}
    registry["clock"]["now"] += TOUCH_CLIENT_TIMEOUT - 1
    assert touch.expired() == []                        # the ping reset the clock


def test_ping_from_an_unknown_client_says_so(registry, caplog):
    assert touch.ping({"client": "ghost"})["status"] == "unknown"
    assert touch.clients() == []                        # a ping never registers
    assert "unregistered client" in caplog.text


def test_ping_requires_a_client_id(registry):
    with pytest.raises(ValueError):
        touch.ping({})


def test_expired_drops_a_silent_client(registry, caplog):
    _post("wall")
    registry["clock"]["now"] += TOUCH_CLIENT_TIMEOUT + 0.1
    assert touch.expired() == ["wall"]
    assert touch.clients() == []
    assert "dropped" in caplog.text


def test_start_spawns_one_daemon_thread(registry, monkeypatch):
    started: list = []

    class FakeThread:
        def __init__(self, target=None, name=None, daemon=None):
            started.append((target, name, daemon))

        def start(self):
            pass

    monkeypatch.setattr(touch.threading, "Thread", FakeThread)
    touch.start(lambda: None)
    assert len(started) == 1 and started[0][1] == "touch-sweeper" and started[0][2] is True


def test_dead_client_timeout_is_longer_than_the_sweep():
    assert 0 < TOUCH_SWEEP_INTERVAL < TOUCH_CLIENT_TIMEOUT


# --- press: proxied back to TouchDesigner ----------------------------------
def test_press_fires_the_button_id_over_osc(registry):
    _post(host="10.0.0.9", port=9000, address="/wall")
    assert touch.press("wall", "intro") == "OK"
    assert registry["sent"] == [("10.0.0.9", 9000, "/wall", ("intro",))]


def test_press_for_an_unknown_client_is_reported(registry):
    assert touch.press("ghost", "intro").startswith("ERR")
    assert registry["sent"] == []


# --- menu tree -------------------------------------------------------------
def test_attach_inserts_touch_after_aoto():
    root = MenuNode("", None, "", children=[
        MenuNode("__pc__", None, "ПК"), MenuNode("__pdq__", None, "PDQ"),
        MenuNode("__aoto__", None, "AOTO"), MenuNode("other", None, "Other")])
    touch.attach(root)
    assert [c.name for c in root.children] == ["__pc__", "__pdq__", "__aoto__", "__touch__", "other"]


def test_tab_without_clients_shows_a_hint(registry):
    kids = touch._touch_children(None)
    assert len(kids) == 1 and isinstance(kids[0], ActionNode)
    assert "нет клиентов" in kids[0].label
    assert kids[0].on_press() == ""                     # pressing it does nothing


def test_tab_lists_one_submenu_per_client(registry):
    _post("wall", label="Стена")
    _post("ceiling", label="Потолок")
    kids = touch._touch_children(None)
    assert [k.name for k in kids] == ["ceiling", "wall"]     # sorted by label
    assert all(isinstance(k, MenuNode) for k in kids)
    assert kids[1].label == "Стена" and kids[1].context == {"client": "wall"}


def test_client_buttons_are_action_nodes_that_press_over_osc(registry):
    _post(host="10.0.0.9", port=9000, address="/wall",
          buttons=[{"id": "intro", "label": "Intro"}, {"id": "clipA", "label": "Клип\nA"}])
    node = MenuNode("wall", None, "Стена", context={"client": "wall"})
    buttons = touch._client_buttons(node)
    assert [b.label for b in buttons] == ["Intro", "Клип\nA"]
    assert all(isinstance(b, ActionNode) and b.after == After.TEXT for b in buttons)

    assert buttons[1].on_press() == "OK"                # the press goes to the client
    assert registry["sent"] == [("10.0.0.9", 9000, "/wall", ("clipA",))]


def test_active_and_colored_buttons_get_deck_colors(registry):
    _post(buttons=[{"id": "on", "active": True}, {"id": "red", "color": "#4a1414"},
                   {"id": "plain"}])
    node = MenuNode("wall", None, "wall", context={"client": "wall"})
    colors = [b.color_fn() for b in touch._client_buttons(node)]
    assert colors[0] == COLORS[Kind.FEEDBACK]           # active -> the green highlight
    assert colors[1] == ("#4a1414", "#ffffff")          # client background + white text
    assert colors[2] is None                            # default kind color


def test_client_buttons_of_an_expired_client_are_empty(registry):
    _post()
    registry["clock"]["now"] += TOUCH_CLIENT_TIMEOUT + 1
    touch.expired()
    node = MenuNode("wall", None, "wall", context={"client": "wall"})
    assert touch._client_buttons(node) == []            # nothing to render, no crash
