"""OSC 1.0 wire encoding: strings, type tags, padding, and the sender."""
import struct

import pytest

from core import osc


# --- _osc_string: null-terminated, zero-padded to 4 bytes ------------------
def test_osc_string_pads_to_multiple_of_four():
    assert osc._osc_string("abc") == b"abc\x00"          # 3+1 = 4, no extra pad
    assert osc._osc_string("ab") == b"ab\x00\x00"        # 2+1 -> pad to 4
    assert osc._osc_string("abcd") == b"abcd\x00\x00\x00\x00"  # 4+1 -> pad to 8
    assert osc._osc_string("") == b"\x00\x00\x00\x00"    # empty still 4 bytes
    assert len(osc._osc_string("hello world")) % 4 == 0


def test_osc_string_is_utf8():
    b = osc._osc_string("ПК")
    assert b.startswith("ПК".encode("utf-8"))
    assert len(b) % 4 == 0 and b.endswith(b"\x00")


# --- _message: type tag string + payload -----------------------------------
def test_message_single_string_arg():
    msg = osc._message("/x", "hi")
    assert msg == osc._osc_string("/x") + osc._osc_string(",s") + osc._osc_string("hi")


def test_message_three_ints_for_color():
    msg = osc._message("/c", 12, 34, 56)
    expected = osc._osc_string("/c") + osc._osc_string(",iii") + struct.pack(">iii", 12, 34, 56)
    assert msg == expected


def test_message_bool_tags_carry_no_payload():
    # T/F args set the type tag but add nothing to the payload.
    assert osc._message("/b", True, False) == osc._osc_string("/b") + osc._osc_string(",TF")


def test_message_float_arg():
    msg = osc._message("/f", 1.5)
    assert msg == osc._osc_string("/f") + osc._osc_string(",f") + struct.pack(">f", 1.5)


def test_message_rejects_unsupported_type():
    with pytest.raises(TypeError):
        osc._message("/x", {"nope": 1})


# --- send / helpers: what actually goes on the wire ------------------------
class FakeSock:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


@pytest.fixture
def sock(monkeypatch):
    s = FakeSock()
    monkeypatch.setattr(osc, "_sock", s)
    return s


def test_send_targets_configured_addr(sock):
    osc.send("/ping")
    (data, addr), = sock.sent
    assert addr == osc._addr
    assert data == osc._osc_string("/ping") + osc._osc_string(",")


def test_send_fails_soft_on_socket_error(monkeypatch):
    class Boom:
        def sendto(self, *a):
            raise OSError("down")

    monkeypatch.setattr(osc, "_sock", Boom())
    osc.send("/x", "y")  # must not raise


def test_set_text_builds_location_address(sock):
    osc.set_text("1", 0, 3, "hello")
    (data, _), = sock.sent
    assert data == osc._message("/location/1/0/3/style/text", "hello")


def test_set_bgcolor_and_color_addresses(sock):
    osc.set_bgcolor("2", 1, 4, 10, 20, 30)
    osc.set_color("2", 1, 4, 40, 50, 60)
    (bg, _), (fg, _) = sock.sent
    assert bg == osc._message("/location/2/1/4/style/bgcolor", 10, 20, 30)
    assert fg == osc._message("/location/2/1/4/style/color", 40, 50, 60)
