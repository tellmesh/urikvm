from __future__ import annotations

from importlib.resources import as_file

from uri_control import CapabilityRegistry

import urikvm


def test_manifest_loads():
    with as_file(urikvm.manifest_path()) as path:
        registry = CapabilityRegistry.from_manifest_files([path])
    assert registry.manifests[0].scheme == "kvm"
    assert len(registry.routes) == 4
    ops = {route.operation for route in registry.routes}
    assert ops == {
        "kvm.monitor.list",
        "kvm.monitor.screenshot",
        "kvm.task.click_text",
        "kvm.task.type_text",
    }
