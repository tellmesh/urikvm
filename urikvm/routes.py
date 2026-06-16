def register(runtime):
    runtime.register('kvm://{host}/monitor/query/list', 'python://urikvm.handlers:monitor_list', kind='query', operation='kvm.monitor.list')
    runtime.register('kvm://{host}/monitor/{monitor}/query/screenshot', 'python://urikvm.handlers:screenshot', kind='query', operation='kvm.monitor.screenshot')
    runtime.register('kvm://{host}/task/command/click-text', 'python://urikvm.handlers:click_text', kind='command', operation='kvm.task.click_text', approval='required', side_effects=True)
    runtime.register('kvm://{host}/task/command/type-text', 'python://urikvm.handlers:type_text', kind='command', operation='kvm.task.type_text', approval='required', side_effects=True)
