from urikvmedge.runtime import Runtime
import urihim, uriocr, urillm, urikvm


def runtime():
    rt = Runtime(events_path='/tmp/urikvm-test-events.jsonl', config={
        'kvm': {'driver': 'mock'},
        'him': {'driver': 'mock'},
        'ocr': {'driver': 'mock'},
        'llm': {'driver': 'mock'},
    })
    urihim.register(rt); uriocr.register(rt); urillm.register(rt); urikvm.register(rt)
    return rt


def test_him_requires_approval():
    res = runtime().call('him://local/mouse/command/click', {'x': 1, 'y': 2})
    assert not res['ok']
    assert res['type'] == 'policy_denied'


def test_kvm_click_text_uses_him_ocr_llm():
    rt = runtime()
    res = rt.call('kvm://local/task/command/click-text', {'text': 'OK'}, {'approved': True})
    assert res['ok']
    assert res['result']['clicked'] is True
    assert res['result']['target_text'] == 'OK'


def test_type_text():
    rt = runtime()
    res = rt.call('kvm://local/task/command/type-text', {'text': 'abc'}, {'approved': True})
    assert res['ok']
    assert res['result']['result']['typed'] == 'abc'
