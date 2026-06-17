from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def config_value(context: dict[str, Any], key: str, default=None):
    cfg = context.get("config") or {}
    return cfg.get(key, default)


def detect_display(context: dict[str, Any]) -> str:
    # Priority: explicit context, env, config default, scan X sockets.
    if context.get("display"):
        return str(context["display"])
    if os.environ.get("URISYS_KVM_DISPLAY"):
        return os.environ["URISYS_KVM_DISPLAY"]
    if os.environ.get("URISYS_RDP_DISPLAY"):
        return os.environ["URISYS_RDP_DISPLAY"]
    if os.environ.get("DISPLAY"):
        return os.environ["DISPLAY"]
    default = config_value(context, "default_display")
    if default:
        return str(default)
    sockets = sorted(Path("/tmp/.X11-unix").glob("X*"))
    if sockets:
        return ":" + sockets[0].name[1:]
    return ":10"


def base_env(context: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env["DISPLAY"] = detect_display(context)
    xauth = (
        context.get("xauthority")
        or os.environ.get("XAUTHORITY")
        or config_value(context, "xauthority")
    )
    if not xauth:
        user = config_value(context, "session_user", "urisys")
        candidate = Path(f"/home/{user}/.Xauthority")
        if candidate.exists():
            xauth = str(candidate)
    if xauth:
        env["XAUTHORITY"] = str(xauth)
    return env


def allow_real(context: dict[str, Any]) -> bool:
    return bool(context.get("allow_real") or os.environ.get("URISYS_ALLOW_REAL") == "1")


def run_cmd(args: list[str], context: dict[str, Any], *, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(args, env=base_env(context), text=True, capture_output=True, timeout=timeout, check=False)


def ensure_screenshot_dir(context: dict[str, Any]) -> Path:
    path = config_value(context, "screenshot_dir", "data/screenshots")
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
