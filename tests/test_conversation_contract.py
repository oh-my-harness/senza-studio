import pytest

from studio_backend.spec import Spec, SpecError
from studio_backend.tools.spec_tools import make_spec_callbacks, _SCHEMAS
from senza_studio_runtime.contract import describe_agent


def example():
    return Spec({"stages": [
        {"name": "reply", "type": "agent", "prompt_template": "{{action}} {{story_id}} {{history}}", "next_on_success": "end"},
        {"name": "end", "type": "terminal"},
    ]})


def test_builder_yaml_reload_contract():
    spec = example()
    callbacks = make_spec_callbacks(spec)
    assert callbacks['set_agent_ui']({"layout": "conversation", "conversation": {
        "message_input": "action", "carry_inputs": ["story_id"], "history_input": "history"
    }, "inputs": {"story_id": {"default": "story_001"}}}, None) == 'Agent UI updated.'
    assert callbacks['validate_spec']({}, None).startswith('Spec is valid')
    reloaded = Spec.from_yaml(spec.to_yaml())
    reloaded.validate()
    assert reloaded.get_current_spec() == spec.get_current_spec()
    info = describe_agent(reloaded.get_current_spec())
    assert info['layout'] == 'conversation'
    assert info['conversation']['history_max_messages'] == 20
    assert info['inputs'][1]['default'] == 'story_001'
    assert 'conversation' in _SCHEMAS['set_agent_ui']['parameters']['properties']


@pytest.mark.parametrize('config', [
    {}, {'message_input': 'missing'}, {'message_input': 'action', 'carry_inputs': ['missing']},
    {'message_input': 'action', 'history_input': 'missing'},
    {'message_input': 'action', 'history_input': 'action'},
    {'message_input': 'action', 'carry_inputs': ['story_id', 'story_id']},
    {'message_input': 'action', 'carry_inputs': ['action']},
    {'message_input': 'action', 'history_max_messages': True},
    {'message_input': 'action', 'history_max_chars': 0},
    {'message_input': 'action', 'history_input': []},
    {'message_input': 'action', 'history_format': 'array'},
])
def test_bad_mapping_rejected_in_tool_and_raw_spec(config):
    spec = example()
    with pytest.raises(SpecError):
        spec.set_agent_ui(conversation=config)
    data = spec.get_current_spec()
    data['ui'] = {'layout': 'conversation', 'conversation': config}
    with pytest.raises(SpecError):
        Spec(data).validate()
    assert describe_agent(data)['error']


def test_history_optional_and_old_layouts_compatible():
    spec = example()
    spec.set_agent_ui(layout='conversation', conversation={'message_input': 'action'})
    spec.validate()
    assert 'history_input' not in describe_agent(spec.get_current_spec())['conversation']
    for layout in ('form', 'dashboard'):
        spec = example()
        spec.set_agent_ui(layout=layout)
        spec.validate()
        info = describe_agent(spec.get_current_spec())
        assert info['layout'] == layout
        assert 'conversation' not in info


def test_invalid_builder_change_is_atomic():
    spec = example()
    before = spec.get_current_spec()
    with pytest.raises(SpecError):
        spec.set_agent_ui(title='changed', layout='conversation', conversation={'message_input': 'missing'})
    assert spec.get_current_spec() == before
