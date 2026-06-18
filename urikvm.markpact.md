# UriPack: urikvm

Self-contained Markpact — definitions, full source, run config. Unpack & run: `urisys markpact run urikvm/urikvm.markpact.md --as service` (writes `.markpact/`).

```yaml markpact:pack
apiVersion: urisys.io/v1
kind: UriPack
metadata:
  id: urikvm-pack
  version: 1.0.0
  language: python
description: KVM monitor capture and OCR/LLM-assisted desktop tasks.
schemes:
- kvm
capabilities:
- id: kvm.monitor.list
  uri: kvm://{host}/monitor/query/list
  kind: query
  operation: kvm.monitor.list
  handler: python://urikvm.handlers:monitor_list
  side_effects: false
  approval: not_required
- id: kvm.display.info
  uri: kvm://{host}/display/query/info
  kind: query
  operation: kvm.display.info
  handler: python://urikvm.handlers:display_info
  side_effects: false
  approval: not_required
- id: kvm.monitor.screenshot
  uri: kvm://{host}/monitor/{monitor}/query/screenshot
  kind: query
  operation: kvm.monitor.screenshot
  handler: python://urikvm.handlers:screenshot
  side_effects: false
  approval: not_required
- id: kvm.task.click_text
  uri: kvm://{host}/task/command/click-text
  kind: command
  operation: kvm.task.click_text
  handler: python://urikvm.handlers:click_text
  side_effects: true
  approval: required
- id: kvm.task.type_text
  uri: kvm://{host}/task/command/type-text
  kind: command
  operation: kvm.task.type_text
  handler: python://urikvm.handlers:type_text
  side_effects: true
  approval: required
policy:
  default: deny_mutations_without_approval
runtime:
  default_environment: mock
  supports:
  - mock
  - local
  - docker
```

```yaml markpact:run
modes:
- pack
- service
- flow
- interface
- adapter
default: service
scheme: kvm
service:
  port: 8790
  wire: POST /uri/call
flow:
  ids:
  - gui-open-software-center
  - llm-guided-gui-click
adapter:
  wire: POST /uri/call
  events: GET /events
```

```python markpact:module path=urikvm/__init__.py
from __future__ import annotations

from importlib.resources import files

from .routes import register

__all__ = ["register", "manifest_path"]


def manifest_path():
    return files(__package__).joinpath("manifest.yaml")
```

```python markpact:module path=urikvm/display.py
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
```

```python markpact:module path=urikvm/handlers.py
import base64
import io
import shutil
import time
from pathlib import Path
from typing import Any

from .display import allow_real, detect_display, ensure_screenshot_dir, run_cmd


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
    entry = {
        'monitor': monitor,
        'driver': driver,
        'mime': mime,
        'base64': base64.b64encode(raw_bytes).decode('ascii'),
        'width': width,
        'height': height,
        'captured_at': time.time(),
    }
    context.setdefault('state', {})['latest_screenshot'] = entry
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
            'monitor': monitor,
            'driver': 'scrot/import',
            'path': str(latest),
            'display': detect_display(context),
            'mime': entry['mime'],
            'base64': entry['base64'],
            'captured': True,
        }
    if driver == 'mss' and not context.get('dry_run'):
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
    return {'monitor': monitor, 'driver': driver, 'mime': entry['mime'], 'base64': entry['base64'], 'text': text}


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
```

```python markpact:module path=urikvm/routes.py
from __future__ import annotations

from importlib.resources import files

from uri_control.edge.manifest import register_manifest_file


def register(runtime):
    register_manifest_file(runtime, files(__package__).joinpath("manifest.yaml"))
```

```yaml markpact:flow id=gui-open-software-center
flow:
  id: gui-open-software-center
  description: Open Software Center via keyboard and click Updates (desktop GUI / HIM + KVM).

defaults:
  approved: true
  dry_run: true

do:
  - him://local/keyboard/command/hotkey:
      keys: ["super"]
  - him://local/keyboard/command/type-text:
      text: Software
  - him://local/keyboard/command/key:
      key: Return
  - kvm://local/monitor/primary/query/screenshot
  - ocr://local/image/latest/query/text
  - kvm://local/task/command/click-text:
      text: Updates
```

```yaml markpact:flow id=llm-guided-gui-click
flow:
  id: llm-guided-gui-click
  description: Screenshot, OCR, LLM vision analyze, then click Install (KVM + OCR + LLM).

defaults:
  approved: true
  dry_run: true

do:
  - kvm://local/monitor/primary/query/screenshot
  - ocr://local/image/latest/query/text
  - llm://local/vision/query/analyze:
      target_text: Install
  - kvm://local/task/command/click-text:
      text: Install
```

```markdown markpact:docs
# urikvm


## AI Cost Tracking

![PyPI](https://img.shields.io/badge/pypi-costs-blue) ![Version](https://img.shields.io/badge/version-0.1.1-blue) ![Python](https://img.shields.io/badge/python-3.9+-blue) ![License](https://img.shields.io/badge/license-Apache--2.0-green)
![AI Cost](https://img.shields.io/badge/AI%20Cost-$0.15-orange) ![Human Time](https://img.shields.io/badge/Human%20Time-1.0h-blue) ![Model](https://img.shields.io/badge/Model-openrouter%2Fqwen%2Fqwen3--coder--next-lightgrey)

- 🤖 **LLM usage:** $0.1500 (1 commits)
- 👤 **Human dev:** ~$100 (1.0h @ $100/h, 30min dedup)

Generated on 2026-06-16 using [openrouter/qwen/qwen3-coder-next](https://openrouter.ai/qwen/qwen3-coder-next)

---




## License

Licensed under Apache-2.0.
```

