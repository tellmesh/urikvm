"""Wayland capture: kvm must use uriscreen's portal backend (mss is black on Wayland)."""

from __future__ import annotations

import sys
import types

import pytest

from urikvm import handlers

_CTX = {"params": {"monitor": "primary"}, "config": {"kvm": {"driver": "mss"}}, "allow_real": True}


def _fake_uriscreen(monkeypatch, *, width=1440, height=900):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    def fake_capture(path, monitor, context, payload):
        path.write_bytes(png)
        return {"path": str(path), "mime": "image/png", "backend_used": "portal",
                "width": width, "height": height}

    backends = types.ModuleType("uriscreen.backends")
    backends.capture_with_fallback = fake_capture
    monkeypatch.setitem(sys.modules, "uriscreen", types.ModuleType("uriscreen"))
    monkeypatch.setitem(sys.modules, "uriscreen.backends", backends)


def test_wayland_delegates_to_portal(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    _fake_uriscreen(monkeypatch)
    out = handlers.screenshot({}, dict(_CTX))
    assert out["driver"] == "portal"
    assert (out["width"], out["height"]) == (1440, 900)
    assert out["base64"]


def test_wayland_without_uriscreen_raises_clear_hint(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(handlers, "_capture_wayland", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="uriscreen"):
        handlers.screenshot({}, dict(_CTX))


def test_x11_does_not_take_wayland_path(monkeypatch):
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    calls = {"wayland": 0}
    monkeypatch.setattr(handlers, "_capture_wayland", lambda *a, **k: calls.__setitem__("wayland", calls["wayland"] + 1) or {})
    try:
        handlers.screenshot({}, dict(_CTX))
    except Exception:
        pass  # mss may be unavailable in CI; we only assert the wayland path was skipped
    assert calls["wayland"] == 0
