"""Shared string constants for button kinds and post-press behavior.

Kept dependency-free so config.py and every core module can import it without
cycles. Values stay plain strings, so they work as dict keys (config.COLORS)
and in `==` comparisons exactly as the bare literals did.
"""


class Kind:
    """A Slot's kind — also the key into config.COLORS."""
    MENU = "menu"          # submenu / folder (drills in)
    COMMAND = "command"    # script or action button
    FEEDBACK = "feedback"  # script button with live output
    BACK = "back"          # navigate up
    HOME = "home"          # jump to the root menu
    PREV = "prev"          # previous page
    NEXT = "next"          # next page
    NAV = "nav"            # paging color
    EMPTY = "empty"        # cleared cell


class After:
    """What happens after an ActionNode's on_press runs."""
    TEXT = "text"          # show the returned text on this button
    RERENDER = "rerender"  # redraw the whole page (content changed)
    BACK = "back"          # pop up one level, then redraw
