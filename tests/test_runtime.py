from __future__ import annotations

from uri_control.edge.runtime import Runtime

import urihim
import urikvm
import urillm
import uriocr


def _pipeline_runtime() -> Runtime:
    rt = Runtime(
        config={
            "kvm": {"driver": "mock"},
            "him": {"driver": "mock"},
            "ocr": {"driver": "mock"},
            "llm": {"driver": "mock"},
        }
    )
    urikvm.register(rt)
    uriocr.register(rt)
    urillm.register(rt)
    urihim.register(rt)
    return rt


def test_monitor_list_mock():
    rt = _pipeline_runtime()
    res = rt.call("kvm://local/monitor/query/list", {}, {"params": {"host": "local"}, "runtime": rt})
    assert res["ok"]
    assert res["result"]["monitors"]


def test_click_text_mock_pipeline():
    rt = _pipeline_runtime()
    ctx = {"approved": True, "params": {"host": "local"}, "runtime": rt}
    res = rt.call("kvm://local/task/command/click-text", {"text": "OK"}, ctx)
    assert res["ok"]
    assert res["result"]["clicked"] is True
