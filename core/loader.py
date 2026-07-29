"""Build the in-memory menu tree from the `menus/` folder hierarchy."""
from __future__ import annotations

import logging
from pathlib import Path

from .config import MENUS_DIR
from .model import CommandNode, MenuNode, children_of, is_feedback, is_script, make_label


def load_tree(base: Path = MENUS_DIR) -> MenuNode:
    root = MenuNode(name="", path=base, label="")
    if base.is_dir():
        _fill(root)
    try:
        from . import aoto, pcbrowser, pdqmenu  # dynamic menus attach here

        pcbrowser.attach(root)   # "ПК": one host at a time
        pdqmenu.attach(root)     # "PDQ": batch deploy to the active list
        aoto.attach(root)        # "AOTO": HTTP control of LED-processor groups
    except Exception as e:  # never let a dynamic menu break the static tree
        logging.getLogger("loader").warning("dynamic menu attach failed: %s", e)
    return root


def _fill(menu: MenuNode) -> None:
    entries = sorted(
        (p for p in menu.path.iterdir() if not p.name.startswith(".")),
        key=lambda p: p.name,
    )
    for p in entries:
        if p.is_dir():
            child = MenuNode(name=p.name, path=p, label=make_label(p.name, True))
            _fill(child)
            menu.children.append(child)
        elif is_script(p):
            menu.children.append(
                CommandNode(
                    name=p.name,
                    path=p,
                    label=make_label(p.name, False),
                    feedback=is_feedback(p),
                )
            )


def resolve(root: MenuNode, path_names: list[str]) -> MenuNode:
    """Walk from `root` following names; fall back to node if a step is stale.

    Uses `children_of` so dynamic (provider) menus are materialized as we walk.
    """
    node = root
    for name in path_names:
        match = next(
            (c for c in children_of(node) if isinstance(c, MenuNode) and c.name == name),
            None,
        )
        if match is None:
            return node
        node = match
    return node
