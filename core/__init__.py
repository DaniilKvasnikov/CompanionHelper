"""Modular Stream Deck / Companion menu system.

The deck is "dumb": every button just reports its (page, row, col) to this
server on press. The server owns all state and logic, and re-renders button
styles back into Companion via its HTTP API. See CLAUDE.md for the big picture.
"""
