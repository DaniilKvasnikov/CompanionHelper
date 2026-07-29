"""Batch PDQ deployment menu, built on the active target list.

A "PDQ" button on the main menu opens a menu for deploying a package to a
whole target list at once (the "ПК" menu, core/pcbrowser.py, stays as the
single-host tool). Inside "PDQ":

  - "Лист"     -> pick the active target list (shared with the "ПК" menu);
  - "Выбор ПК" -> toggle individual hosts in/out of the deploy set; all
    enabled by default, ✓/✗ marker shows state, color shows ping;
  - "Область"  -> toggle the deploy scope: the whole list, or only enabled hosts;
  - one button per package -> deploys it to the current scope, in one PDQ call.

The catalog (lists / packages / members / ping) is owned and cached by
core/pcbrowser.py; this module only adds the per-list "disabled" set and the
scope flag, and reads everything else from there. Deploys go through core/pdq.
Providers stay cheap (cache reads only); the deploy — the one blocking call —
runs in the button's on_press, not during a render.
"""
from __future__ import annotations

import threading

from . import pcbrowser, pdq
from .config import PC_OFF
from .constants import After, Kind
from .model import ActionNode, MenuNode
from .runner import RunResult

_lock = threading.RLock()
_disabled: dict[str, set[str]] = {}   # per target-list: hosts switched OFF (absent -> enabled)
_scope_active = False                 # False -> whole list; True -> only enabled hosts


# --- enable/disable + scope state -----------------------------------------
def is_enabled(host: str) -> bool:
    """A host deploys unless it was explicitly toggled off in the active list."""
    name = pcbrowser.active_list()
    with _lock:
        return not (name and host in _disabled.get(name, set()))


def toggle_host(host: str) -> None:
    name = pcbrowser.active_list()
    if not name:
        return
    with _lock:
        off = _disabled.setdefault(name, set())
        off.discard(host) if host in off else off.add(host)


def scope_active() -> bool:
    with _lock:
        return _scope_active


def toggle_scope() -> None:
    global _scope_active
    with _lock:
        _scope_active = not _scope_active


def targets() -> list[str]:
    """Hosts a package deploys to under the current scope."""
    hosts = pcbrowser.members()
    if scope_active():
        hosts = [h for h in hosts if is_enabled(h)]
    return hosts


# --- menu tree (providers) -------------------------------------------------
def attach(root: MenuNode) -> None:
    """Insert the PDQ batch menu right after the "ПК" menu on the main menu."""
    idx = 1 if root.children and getattr(root.children[0], "name", None) == "__pc__" else 0
    root.children.insert(
        idx, MenuNode(name="__pdq__", path=None, label="PDQ", provider=_pdq_children)
    )


def _pdq_children(node) -> list:
    active = pcbrowser.active_list() or "-"
    scope = "активные" if scope_active() else "весь список"
    kids: list = [
        MenuNode(name="__pdq_list__", path=None, label=f"Лист:\n{active}",
                 provider=pcbrowser.list_picker),
        MenuNode(name="__pdq_pcs__", path=None, label="Выбор ПК",
                 provider=_pc_toggle_picker),
        ActionNode(name="__pdq_scope__", label=f"Область:\n{scope}",
                   kind=Kind.NAV, after=After.RERENDER, on_press=toggle_scope),
    ]
    kids += [
        ActionNode(name=pkg, label=pkg, kind=Kind.COMMAND,
                   after=After.TEXT, on_press=lambda p=pkg: _deploy(p))
        for pkg in pcbrowser.packages()
    ]
    return kids


def _pc_toggle_picker(node) -> list:
    out: list = []
    for host in pcbrowser.members():
        label = ("✓ " if is_enabled(host) else "✗ ") + pcbrowser.host_label(host)
        out.append(
            ActionNode(name=host, label=label, kind=Kind.COMMAND,
                       after=After.RERENDER,
                       on_press=lambda h=host: toggle_host(h),
                       color_fn=lambda h=host: _toggle_color(h))
        )
    return out


def _toggle_color(host: str):
    return pcbrowser.pc_color(host) if is_enabled(host) else PC_OFF


def _deploy(package: str) -> str:
    hosts = targets()
    if not hosts:
        return "нет ПК"
    return RunResult(*pdq.run(pdq.deploy_args(package, hosts))).summary()
