import asyncio
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import agents
import app
import graph
import models
from schemas import AgentError, Summary


@pytest.fixture
def session():
    return {"id": "test", "scenario_id": "aftersales", "title": "售后服务助手", "mode": "demo",
            "messages": [{"id": "M1", "role": "assistant", "content": "想做一个售后助手。"}],
            "notes": [], "documents": [], "revision": 0}


def interviewed(session):
    session['messages'] += [{'id': 'M2', 'role': 'user', 'content': '给谁用？'},
                            {'id': 'M3', 'role': 'assistant', 'content': '给客服使用。'}]
    session['revision'] = 1
    return session


def test_graph_routes_chat_without_summarizing_and_no_input_mutation(session, monkeypatch):
    async def unexpected(*args):
        pytest.fail('chat must not invoke summary')
    monkeypatch.setattr(agents, 'summarize', unexpected)
    before = copy.deepcopy(session)
    output = asyncio.run(graph.run_workflow('chat', session, '目标用户是谁？'))
    assert output['trace'] == ['await_user', 'record_user', 'prepare_context', 'stakeholder_agent', 'validate_reply', 'record_assistant']
    assert '客服' in output['answer']
    assert output['session']['messages'][-1]['content'] == output['answer']
    assert before == session


def test_summary_node_has_only_public_context_and_full_validation_path(session, monkeypatch):
    session = interviewed(session)
    session['notes'] = [{'id': 'N1', 'text': '自动退款', 'category': '范围与边界'}]
    async def draft(context, brief):
        assert set(context) == {'mode', 'scenario_id', 'messages', 'notes'}
        assert set(brief) == {'title', 'initial'}
        assert 'facts' not in json.dumps([context, brief])
        return {'overview': '摘要', 'requirements': [{'section': '范围与边界', 'text': '自动退款', 'status': '已确认', 'sources': ['N1']}], 'questions': []}
    monkeypatch.setattr(agents, 'summarize', draft)
    output = asyncio.run(graph.run_workflow('document', session))
    assert output['trace'] == ['await_user', 'prepare_context', 'summary_agent', 'validate_evidence', 'assemble_document', 'save_draft']
    assert output['session']['phase'] == 'reviewing'
    document = output['document']
    assert document['result']['requirements'][0]['status'] == '待确认'
    session['notes'][0]['text'] = 'changed'
    assert document['evidence']['notes'][0]['text'] == '自动退款'
    assert document['version'] == 1 and document['input_revision'] == 1


def test_bad_evidence_stops_graph_before_document(session, monkeypatch):
    session = interviewed(session)
    async def draft(*args):
        return {'overview': '摘要', 'requirements': [{'section': '范围与边界', 'text': '幻觉', 'status': '已确认', 'sources': ['M999']}], 'questions': []}
    monkeypatch.setattr(agents, 'summarize', draft)
    with pytest.raises(AgentError, match='不存在'):
        asyncio.run(graph.run_workflow('document', session))
    assert session['documents'] == []


def test_empty_reply_is_rejected_in_graph(session, monkeypatch):
    async def empty(*args):
        return '   '
    monkeypatch.setattr(agents, 'stakeholder', empty)
    with pytest.raises(AgentError, match='有效回复'):
        asyncio.run(graph.run_workflow('chat', session, '谁使用？'))


def test_each_graph_invocation_has_fresh_trace(session):
    async def invoke_twice():
        return await graph.run_workflow('chat', session, '谁用？'), await graph.run_workflow('document', interviewed(session))
    chat, summary = asyncio.run(invoke_twice())
    assert len(chat['trace']) == 6 and len(summary['trace']) == 6
    assert 'stakeholder_agent' not in summary['trace']


def test_only_project_deepseek_key_no_legacy_fallback(tmp_path, monkeypatch):
    local = tmp_path / 'agent-learning'; local.mkdir()
    sibling = tmp_path / 'multi-agent-task-studio'; sibling.mkdir()
    (sibling / '.env').write_text('OPENAI_API_KEY=do-not-read\n', encoding='utf-8')
    monkeypatch.setattr(models, 'ROOT', local)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'do-not-use')
    monkeypatch.setenv('MODEL_NAME', 'wrong-model')
    assert not models.config()['key']
    (local / '.env').write_text('DEEPSEEK_API_KEY=project-test-key\nMODEL_NAME=wrong-model', encoding='utf-8')
    assert models.config()['key'] == 'project-test-key'
    assert models.config()['model'] == 'deepseek-flash'
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'explicit-test-key')
    assert models.config()['key'] == 'explicit-test-key'


def test_no_key_blocks_network_and_bootstrap_marks_unconfigured(tmp_path, monkeypatch, session):
    monkeypatch.setattr(models, 'ROOT', tmp_path)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail('must not open a network client without a key')
    monkeypatch.setattr(models.httpx, 'AsyncClient', forbidden)
    session['mode'] = 'live'
    with pytest.raises(AgentError, match='DEEPSEEK_API_KEY'):
        asyncio.run(graph.run_workflow('chat', session, '谁用？'))
    data = app.bootstrap()
    assert data['engine'] == 'LangGraph'
    assert data['model']['name'] == 'DeepSeek-V4.1-Flash'
    assert data['model']['ready'] is False
    assert 'key' not in data['model']


def test_both_live_agents_use_same_deepseek_request_contract(monkeypatch, session):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-test-key')
    captured = []
    def respond(request):
        body = json.loads(request.content)
        captured.append(body)
        assert str(request.url) == 'https://api.deepseek.com/chat/completions'
        assert request.headers['Authorization'] == 'Bearer fake-test-key'
        if 'response_format' in body:
            content = json.dumps({'overview': '访谈摘要', 'requirements': [{'section': '目标与用户', 'text': '给客服使用。', 'status': '已确认', 'sources': ['M3']}], 'questions': []})
        else:
            content = '给客服使用。'
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(models.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    session['mode'] = 'live'
    async def run():
        answer = await graph.run_workflow('chat', session, '给谁用？')
        assert answer['answer'] == '给客服使用。'
        return await graph.run_workflow('document', interviewed(session))
    result = asyncio.run(run())
    assert result['document']['result']['requirements'][0]['status'] == '已确认'
    assert len(captured) == 2
    assert all(p['model'] == 'deepseek-flash' and p['thinking'] == {'type': 'disabled'} for p in captured)
    assert captured[1]['response_format'] == {'type': 'json_object'}
    assert 'facts' not in captured[1]['messages'][1]['content']


@pytest.mark.parametrize('status,finish,content', [(401, 'stop', 'secret'), (200, 'length', 'cut'), (200, 'stop', '')])
def test_model_error_is_safe_and_not_committed(monkeypatch, session, status, finish, content):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-test-key')
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={'choices': [{'finish_reason': finish, 'message': {'content': content}}]}))
    monkeypatch.setattr(models.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=transport, **kwargs))
    session['mode'] = 'live'
    with pytest.raises(AgentError) as error:
        asyncio.run(graph.run_workflow('chat', session, '谁使用？'))
    assert 'fake-test-key' not in str(error.value)
    assert len(session['messages']) == 1


def test_http_endpoints_really_run_the_compiled_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'DB', tmp_path / 'api.sqlite3')
    app.locks.clear()
    with TestClient(app.app) as client:
        sid = client.post('/api/sessions', json={'scenario_id': 'itdesk', 'mode': 'demo'}).json()['id']
        response = client.post(f'/api/sessions/{sid}/messages', json={'content': '目标用户是谁？', 'request_id': 'r1'})
        assert response.status_code == 200
        assert [n['id'] for n in response.json()['last_run']['nodes']] == ['await_user', 'record_user', 'prepare_context', 'stakeholder_agent', 'validate_reply', 'record_assistant']
        document = client.post(f'/api/sessions/{sid}/documents').json()
        assert document['last_run']['nodes'][-1]['id'] == 'save_draft'
        assert document['documents'][0]['version'] == 1


def test_real_subgraphs_and_compact_parent_topology():
    compiled = graph.build_graph()
    children = dict(compiled.get_subgraphs())
    assert set(children) == {'clarification', 'documentation'}
    parent = compiled.get_graph(xray=False)
    assert 'stakeholder_agent' not in parent.nodes
    assert 'summary_agent' not in parent.nodes
    assert 'stakeholder_agent' in children['clarification'].get_graph().nodes
    assert 'record_notes' in children['clarification'].get_graph().nodes
    assert 'summary_agent' in children['documentation'].get_graph().nodes
    assert 'save_draft' in children['documentation'].get_graph().nodes
    expanded = compiled.get_graph(xray=True)
    assert len(expanded.nodes) > len(parent.nodes)


def test_chinese_diagram_labels_come_from_actual_graph():
    from render_native_graph import chinese_topology
    topology = chinese_topology(graph.workflow)
    assert topology.nodes['clarification'].name == '需求澄清子图'
    assert topology.nodes['documentation'].name == '文档生成子图'
    assert {(e.source,e.target) for e in topology.edges} == {(e.source,e.target) for e in graph.workflow.get_graph().edges}


def test_nested_checkpoint_recovers_after_unexpected_interruption(tmp_path, monkeypatch):
    monkeypatch.setattr(app, 'DB', tmp_path / 'nested.sqlite3')
    app.locks.clear()
    original = agents.stakeholder
    async def crash(*args):
        raise RuntimeError('simulated worker interruption')
    with TestClient(app.app) as client:
        sid = client.post('/api/sessions', json={'scenario_id':'itdesk','mode':'demo'}).json()['id']
        monkeypatch.setattr(agents, 'stakeholder', crash)
        with pytest.raises(RuntimeError, match='simulated worker'):
            client.post(f'/api/sessions/{sid}/messages', json={'content':'谁使用？','request_id':'recover'})
        assert len(client.get(f'/api/sessions/{sid}').json()['messages']) == 2
        monkeypatch.setattr(agents, 'stakeholder', original)
        response = client.post(f'/api/sessions/{sid}/messages', json={'content':'谁使用？','request_id':'recover'})
        assert response.status_code == 200
        result = response.json()
        assert len(result['messages']) == 3
        assert result['requests'] == ['recover']
        assert 'pending_chat' not in result
