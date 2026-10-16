import pytest
from PIL import Image

from pdf_helper import capture
from pdf_helper.capture import capture_window, is_flat
from pdf_helper.errors import UserFacingError


def test_is_flat():
    assert is_flat(Image.new("RGB", (10, 10), "black"))
    img = Image.new("RGB", (10, 10), "black")
    img.putpixel((0, 0), (255, 255, 255))
    assert not is_flat(img)


def test_too_small_rect_raises(monkeypatch):
    monkeypatch.setattr(capture, "window_rect", lambda h: (0, 0, 150, 300))
    monkeypatch.setattr(capture, "_window_title", lambda h: "Tiny flyout")
    with pytest.raises(UserFacingError, match="Tiny flyout.*too small"):
        capture_window(123)


def test_falls_back_to_screen_when_print_window_is_flat(monkeypatch):
    monkeypatch.setattr(capture, "window_rect", lambda h: (0, 0, 400, 400))
    monkeypatch.setattr(capture, "_print_window", lambda h, w, ht: Image.new("RGB", (400, 400), "black"))
    monkeypatch.setattr(capture, "_grab_screen", lambda h, rect: Image.new("RGB", (400, 400), "white"))
    img, method = capture_window(1)
    assert method == "screen"
