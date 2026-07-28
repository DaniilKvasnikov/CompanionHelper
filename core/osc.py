"""Minimal OSC 1.0 sender over UDP (fire-and-forget, no dependency).

Used for the hot path — changing button text — which is far cheaper than an
HTTP round-trip. Companion listens for OSC on OSC_PORT (default 12321):

    /location/<page>/<row>/<column>/style/text  <text>
"""
from __future__ import annotations

import logging
import socket
import struct

from .config import OSC_HOST, OSC_PORT

log = logging.getLogger("osc")

_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_addr = (OSC_HOST, OSC_PORT)


def _osc_string(s: str) -> bytes:
    """UTF-8, null-terminated, zero-padded to a multiple of 4 bytes."""
    b = s.encode("utf-8") + b"\x00"
    pad = (-len(b)) % 4
    return b + b"\x00" * pad


def _message(address: str, *args) -> bytes:
    tags = ","
    payload = b""
    for a in args:
        if isinstance(a, str):
            tags += "s"
            payload += _osc_string(a)
        elif isinstance(a, bool):
            tags += "T" if a else "F"
        elif isinstance(a, int):
            tags += "i"
            payload += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"
            payload += struct.pack(">f", a)
        else:
            raise TypeError(f"unsupported OSC arg type: {type(a)}")
    return _osc_string(address) + _osc_string(tags) + payload


def send(address: str, *args) -> None:
    """Fire an OSC message. Fails soft: logs and continues on error."""
    try:
        _sock.sendto(_message(address, *args), _addr)
    except OSError as e:
        log.warning("osc %s failed: %s", address, e)


def set_text(page, row, col, text: str) -> None:
    send(f"/location/{page}/{row}/{col}/style/text", text)


def set_bgcolor(page, row, col, r: int, g: int, b: int) -> None:
    send(f"/location/{page}/{row}/{col}/style/bgcolor", r, g, b)


def set_color(page, row, col, r: int, g: int, b: int) -> None:
    send(f"/location/{page}/{row}/{col}/style/color", r, g, b)
