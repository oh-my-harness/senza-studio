"""Real WebSocket + WorkflowEngine integration, deterministic tools, no model cost."""
import json

from fastapi.testclient import TestClient

from senza_studio_runtime.serve import create_app as export_app
from studio_backend.app import _reset_state, create_app
from studio_backend.config import StudioConfig
from studio_backend.export import export_project
from studio_backend.project import Project
from studio_backend.spec import Spec
from studio_backend.tools.spec_tools import make_spec_callbacks


def test_builder_disk_contract_studio_and_actual_export_two_plays(tmp_path):
    _reset_state()
    cfg = StudioConfig(home_dir=str(tmp_path / 'home'), api_token='conversation-test-token-0123456789', api_key='unused', model='unused')
    project = Project.create(cfg, 'Generic conversation')
    spec = Spec({'stages': [
        {'name': 'reply', 'type': 'tool', 'tool': 'echo', 'tool_args': {'message': '{{message}}', 'course': '{{course}}', 'history': '{{history}}'}, 'next_on_success': 'done'},
        {'name': 'done', 'type': 'terminal', 'message': 'Finished'},
    ]})
    cb = make_spec_callbacks(spec)
    assert cb['set_agent_ui']({'layout': 'conversation', 'conversation': {'message_input': 'message', 'carry_inputs': ['course'], 'history_input': 'history'}}, None) == 'Agent UI updated.'
    spec.validate()
    project.save_spec(spec)
    (project.path / 'tools' / 'registry.py').write_text('import json\ndef echo(args):\n    return json.dumps(args, ensure_ascii=False)\ndef get_tools():\n    return {"echo": echo}\n')
    target, _, _ = export_project(project, spec)
    assert Spec.from_yaml((target / 'pipeline.yaml').read_text()).get_current_spec() == spec.get_current_spec()
    studio = TestClient(create_app(cfg), headers={'Authorization': f'Bearer {cfg.api_token}'})
    exported = TestClient(export_app(target / 'pipeline.yaml', target / 'webui' / 'dist'))
    pid = project.meta['id']
    response = exported.get('/api/agent')
    assert response.json() == studio.get(f'/api/projects/{pid}/agent').json()
    assert response.headers['X-Senza-Agent-Scope'].startswith('export:')
    assert response.json()['conversation']['history_input'] == 'history'
    for client, route, verb in ((studio, f'/ws/projects/{pid}', 'play'), (exported, '/ws/run', 'start')):
        with client.websocket_connect(route) as ws:
            for message, history in [('first', '[]'), ('second', '[{"role":"user","content":"first"}]')]:
                ws.send_json({'type': verb, 'inputs': {'message': message, 'course': 'math', 'history': history}})
                outputs = []
                while True:
                    event = ws.receive_json()
                    assert event['type'] not in ('error', 'failed'), event
                    if event['type'] == 'step_finished' and event['step_id'] == 'reply':
                        outputs.append(json.loads(event['output']))
                    if event['type'] == 'workflow_done':
                        assert event['state'] == 'succeeded'
                        break
                assert outputs == [{'message': message, 'course': 'math', 'history': history}]
    # Scope stays stable across restarts, and changes for another agent.
    scope = response.headers['X-Senza-Agent-Scope']
    assert TestClient(export_app(target / 'pipeline.yaml')).get('/api/agent').headers['X-Senza-Agent-Scope'] == scope
    manifest = target / 'agent.json'
    content = json.loads(manifest.read_text()); content['conversation_storage_id'] = 'another-project'; manifest.write_text(json.dumps(content))
    assert TestClient(export_app(target / 'pipeline.yaml')).get('/api/agent').headers['X-Senza-Agent-Scope'] != scope
    _reset_state()


def test_studio_conversation_build_error_preserves_player_and_reports_play_source(tmp_path, monkeypatch):
    _reset_state()
    cfg = StudioConfig(home_dir=str(tmp_path / 'home'), api_token='conversation-test-token-0123456789', api_key='unused', model='unused')
    project = Project.create(cfg, 'Failure test')
    spec = Spec({'stages': [{'name': 'done', 'type': 'terminal', 'prompt_template': '{{message}}'}]})
    spec.set_agent_ui(layout='conversation', conversation={'message_input': 'message'})
    project.save_spec(spec)
    def fail(*args, **kwargs):
        raise RuntimeError('construction failed')
    monkeypatch.setattr('studio_backend.app.PlaySession.play', fail)
    client = TestClient(create_app(cfg), headers={'Authorization': f'Bearer {cfg.api_token}'})
    with client.websocket_connect(f'/ws/projects/{project.meta["id"]}') as ws:
        ws.send_json({'type': 'play', 'inputs': {'message': 'hello'}})
        while True:
            event = ws.receive_json()
            if event['type'] == 'error':
                assert event['source'] == 'play'
                assert 'construction failed' in event['message']
                break
    _reset_state()
