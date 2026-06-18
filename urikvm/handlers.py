import base64
import io
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .display import allow_real, detect_display, ensure_screenshot_dir, run_cmd


def _is_wayland() -> bool:
    return (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


def _capture_wayland(monitor, context, payload):
    """Wayland capture via uriscreen's portal/vdisplay backend chain (with mss-black
    retry). mss alone returns black frames on Wayland, so reuse the proven screen pack.
    Returns a result dict, or None when uriscreen is unavailable (caller falls back)."""
    try:
        from uriscreen.backends import capture_with_fallback
    except Exception:
        return None
    tmp = Path("/tmp/urikvm-wayland.png")
    cap = capture_with_fallback(tmp, 1, context, payload)
    png = Path(cap["path"]).read_bytes()
    backend = cap.get("backend_used") or cap.get("backend") or "portal"
    entry = _store_screenshot(
        context, monitor, backend, "image/png", png, cap.get("width"), cap.get("height")
    )
    return {
        "image_id": entry["image_id"],
        "monitor": monitor,
        "driver": backend,
        "mime": entry["mime"],
        "base64": entry["base64"],
        "width": cap.get("width"),
        "height": cap.get("height"),
    }


def _profile(context):
    cfg = context.get('config', {}) or {}
    return cfg.get('kvm') or cfg


def display_info(payload, context):
    display = detect_display(context)
    res = run_cmd(['xdpyinfo'], {**context, 'display': display}, timeout=5)
    screen_line = None
    for line in res.stdout.splitlines():
        if 'dimensions:' in line:
            screen_line = line.strip()
            break
    return {
        'display': display,
        'available': res.returncode == 0,
        'dimensions': screen_line,
        'error': res.stderr.strip() if res.returncode != 0 else None,
    }


def _tiny_png() -> bytes:
    return bytes.fromhex(
        '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
        '0000000a49444154789c636000000200015d0b2a0000000049454e44ae426082'
    )


def _store_screenshot(context, monitor, driver, mime, raw_bytes, width=None, height=None):
    image_id = f"shot-{uuid.uuid4().hex[:12]}"
    entry = {
        'image_id': image_id,
        'monitor': monitor,
        'driver': driver,
        'mime': mime,
        'base64': base64.b64encode(raw_bytes).decode('ascii'),
        'width': width,
        'height': height,
        'captured_at': time.time(),
    }
    state = context.setdefault('state', {})
    state['latest_screenshot'] = entry
    state.setdefault('images', {})[image_id] = entry
    return entry


def monitor_list(payload, context):
    monitors = _profile(context).get('monitors') or [{'id': 'primary', 'width': 1280, 'height': 720}]
    return {'monitors': monitors, 'driver': _profile(context).get('driver', 'mock')}


def screenshot(payload, context):
    monitor = context.get('params', {}).get('monitor', 'primary')
    profile = _profile(context)
    driver = profile.get('driver', 'mock')
    if driver in ('scrot', 'scrot/import') and not context.get('dry_run') and allow_real(context):
        out_dir = ensure_screenshot_dir(context)
        latest = out_dir / 'latest.png'
        tmp = Path('/tmp/urikvm-latest.png')
        res = run_cmd(['scrot', str(tmp)], context, timeout=10)
        if res.returncode != 0:
            res2 = run_cmd(['import', '-window', 'root', str(tmp)], context, timeout=10)
            if res2.returncode != 0:
                raise RuntimeError(res.stderr.strip() or res2.stderr.strip() or 'screenshot failed')
        if not tmp.exists() or tmp.stat().st_size < 128:
            raise RuntimeError('screenshot produced empty image')
        shutil.copy2(tmp, latest)
        tmp.unlink(missing_ok=True)
        raw = latest.read_bytes()
        entry = _store_screenshot(context, monitor, 'scrot/import', 'image/png', raw)
        return {
            'image_id': entry['image_id'],
            'monitor': monitor,
            'driver': 'scrot/import',
            'path': str(latest),
            'display': detect_display(context),
            'mime': entry['mime'],
            'base64': entry['base64'],
            'captured': True,
        }
    # Wayland-aware capture: mss returns black frames on Wayland, so on a Wayland session
    # (or explicit auto/portal driver) delegate to uriscreen's portal/vdisplay backend.
    if (
        driver in ('mss', 'auto', 'portal')
        and not context.get('dry_run')
        and (_is_wayland() or driver in ('auto', 'portal'))
    ):
        if not context.get('allow_real'):
            raise PermissionError('real screenshot requires context.allow_real=true')
        wl = _capture_wayland(monitor, context, payload)
        if wl is not None:
            return wl
        # uriscreen not installed; on Wayland mss would be black — surface a clear hint.
        if _is_wayland():
            raise RuntimeError(
                'Wayland capture needs uriscreen (portal backend): pip install "urikvm[real]" or uriscreen'
            )
    if driver in ('mss', 'auto') and not context.get('dry_run'):
        if not context.get('allow_real'):
            raise PermissionError('real screenshot requires context.allow_real=true')
        try:
            import mss  # type: ignore
            from PIL import Image  # type: ignore
        except Exception as exc:
            raise RuntimeError('mss driver requires: pip install mss pillow') from exc
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            img = Image.frombytes('RGB', (shot.width, shot.height), shot.rgb)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            png = buf.getvalue()
            entry = _store_screenshot(context, monitor, driver, 'image/png', png, shot.width, shot.height)
            return {
                'image_id': entry['image_id'],
                'monitor': monitor,
                'driver': driver,
                'mime': entry['mime'],
                'base64': entry['base64'],
                'width': shot.width,
                'height': shot.height,
            }
    text = f'Mock screenshot {monitor} {time.time()} with buttons: Start OK Cancel'
    raw = text.encode('utf-8')
    entry = _store_screenshot(context, monitor, driver, 'text/plain', raw)
    return {
        'image_id': entry['image_id'],
        'monitor': monitor,
        'driver': driver,
        'mime': entry['mime'],
        'base64': entry['base64'],
        'text': text,
    }


def click_text(payload, context):
    runtime = context['runtime']
    host = context.get('params', {}).get('host', 'local')
    text = payload.get('text') or payload.get('target_text')
    if not text:
        raise ValueError('payload.text is required')
    if payload.get('skip_screenshot'):
        shot = {'ok': True, 'result': context.get('state', {}).get('latest_screenshot')}
    else:
        shot = runtime.call(f'kvm://{host}/monitor/primary/query/screenshot', {}, {**context, 'approved': True})
    if not shot.get('ok'):
        return {'clicked': False, 'reason': 'screenshot failed', 'screenshot': shot}
    ocr = runtime.call(f'ocr://{host}/image/latest/query/text', {}, context)
    llm_result = runtime.call(
        f'llm://{host}/vision/query/analyze',
        {'goal': f'click {text}', 'target_text': text, 'ocr': ocr.get('result') or {}, 'tokens': (ocr.get('result') or {}).get('tokens')},
        context,
    )
    action = (llm_result.get('result') or {})
    if action.get('action') != 'click' and not action.get('x'):
        action = {'action': 'click', 'x': 160, 'y': 120, 'target_text': text}
    click = runtime.call(
        f'him://{host}/mouse/command/click',
        {'x': action.get('x', 160), 'y': action.get('y', 120), 'button': payload.get('button', 'left')},
        {**context, 'approved': True},
    )
    click_body = click.get('result') or {}
    clicked = bool(click.get('ok'))
    return {
        'clicked': clicked,
        'target_text': text,
        'reason': None if clicked else (click.get('error') or click_body.get('reason') or 'click failed'),
        'x': action.get('x'),
        'y': action.get('y'),
        'screenshot': shot.get('result'),
        'ocr': ocr.get('result'),
        'llm': action,
        'analysis': action,
        'click': click_body,
        'pipeline': {
            'screenshot': {'ok': bool(shot.get('ok')), 'result': shot.get('result')},
            'ocr': {'ok': bool(ocr.get('ok')), 'result': ocr.get('result')},
            'llm': {'ok': bool(llm_result.get('ok')), 'result': action},
            'him': {'ok': bool(click.get('ok')), 'result': click_body},
        },
    }


def type_text(payload, context):
    runtime = context['runtime']
    host = context.get('params', {}).get('host', 'local')
    text = payload.get('text', '')
    return runtime.call(f'him://{host}/keyboard/command/type', {'text': text}, {**context, 'approved': True})
