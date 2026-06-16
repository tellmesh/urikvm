import base64
import io
import time


def _profile(context):
    return context.get('config', {}).get('kvm', {})


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
    driver = _profile(context).get('driver', 'mock')
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
    analysis = runtime.call(
        f'llm://{host}/vision/query/analyze',
        {'goal': f'click {text}', 'target_text': text, 'ocr': ocr.get('result') or {}},
        context,
    )
    action = (analysis.get('result') or {})
    if action.get('action') != 'click':
        return {'clicked': False, 'reason': 'no click action', 'screenshot': shot.get('result'), 'ocr': ocr.get('result'), 'analysis': action}
    click = runtime.call(
        f'him://{host}/mouse/command/click',
        {'x': action['x'], 'y': action['y'], 'button': payload.get('button', 'left')},
        {**context, 'approved': True},
    )
    return {
        'clicked': bool(click.get('ok')),
        'target_text': action.get('target_text'),
        'x': action.get('x'),
        'y': action.get('y'),
        'screenshot': shot.get('result'),
        'ocr': ocr.get('result'),
        'analysis': action,
        'click': click,
    }


def type_text(payload, context):
    runtime = context['runtime']
    host = context.get('params', {}).get('host', 'local')
    text = payload.get('text', '')
    return runtime.call(f'him://{host}/keyboard/command/type', {'text': text}, {**context, 'approved': True})
