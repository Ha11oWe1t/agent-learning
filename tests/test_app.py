import asyncio
import copy
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server
import agents
from scenarios import SCENARIOS, scenario_by_id


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB", tmp_path / "test.sqlite3")
    server.locks.clear()
    with TestClient(server.app) as client:
        yield client


def create(client):
    response = client.post('/api/sessions', json={'scenario_id': 'aftersales', 'mode': 'demo'})
    assert response.status_code == 200
    return response.json()


def chat(client, sid, content='谁用？第一期范围是什么？', rid='r1'):
    return client.post(f'/api/sessions/{sid}/messages', json={'content': content, 'request_id': rid})


def test_public_bootstrap_has_no_hidden_facts_or_keys(client):
    data = client.get('/api/bootstrap').json()
    assert len(data['scenarios']) == len(SCENARIOS)
    assert all('facts' not in s for s in data['scenarios'])
    assert 'key' not in data['model'] and 'base' not in data['model']
    assert client.get('/.env').status_code == 404
    assert client.get('/').status_code == 200


def test_full_workflow_persistence_and_markdown(client):
    session = create(client); sid = session['id']
    session = chat(client, sid).json()
    assert len(session['messages']) == 3
    note = client.post(f'/api/sessions/{sid}/notes', json={'text': '我希望增加自动退款', 'category': '范围与边界'})
    assert note.status_code == 200
    response = client.post(f'/api/sessions/{sid}/documents')
    assert response.status_code == 200
    doc = response.json()['documents'][0]
    notes = [r for r in doc['result']['requirements'] if 'N1' in r['sources']]
    assert notes[0]['status'] == '待确认'
    assert not any('50 个' in r['text'] for r in doc['result']['requirements'])
    exported = client.get(f'/api/sessions/{sid}/documents/1/markdown')
    assert '来源快照' in exported.text and 'N1' in exported.text
    with TestClient(server.app) as reopened:
        assert reopened.get(f'/api/sessions/{sid}').json()['documents'] == [doc]


def test_idempotent_chat_and_generation(client):
    sid = create(client)['id']
    chat(client, sid); chat(client, sid)
    assert len(client.get(f'/api/sessions/{sid}').json()['messages']) == 3
    for _ in range(2):
        assert client.post(f'/api/sessions/{sid}/documents').status_code == 200
    assert len(client.get(f'/api/sessions/{sid}').json()['documents']) == 1


def test_notes_edit_delete_and_immutable_versions(client):
    sid = create(client)['id']; chat(client, sid)
    client.post(f'/api/sessions/{sid}/notes', json={'text': '初始想法', 'category': '范围与边界'})
    initial = client.post(f'/api/sessions/{sid}/documents').json()['documents'][0]
    client.put(f'/api/sessions/{sid}/notes/N1', json={'text': '修改后的想法', 'category': '验收标准'})
    newer = client.post(f'/api/sessions/{sid}/documents').json()
    assert len(newer['documents']) == 2
    assert newer['documents'][0] == initial
    assert newer['documents'][1]['evidence']['notes'][0]['text'] == '修改后的想法'
    client.delete(f'/api/sessions/{sid}/notes/N1')
    added = client.post(f'/api/sessions/{sid}/notes', json={'text': '新的笔记', 'category': '验收标准'}).json()
    assert added['notes'][0]['id'] == 'N2'
    assert added['revision'] > added['documents'][-1]['input_revision']


def test_failed_model_preserves_state_and_retry(client, monkeypatch):
    sid = create(client)['id']
    original = agents.stakeholder
    async def fail(*args):
        raise agents.AgentError('模型响应超时')
    monkeypatch.setattr(agents, 'stakeholder', fail)
    assert chat(client, sid).status_code == 502
    assert len(client.get(f'/api/sessions/{sid}').json()['messages']) == 2
    monkeypatch.setattr(agents, 'stakeholder', original)
    assert chat(client, sid).status_code == 200


def test_failed_summary_does_not_save_partial_document(client, monkeypatch):
    sid = create(client)['id']; chat(client, sid)
    async def fail(*args):
        raise agents.AgentError('格式不符合要求')
    monkeypatch.setattr(agents, 'summarize', fail)
    assert client.post(f'/api/sessions/{sid}/documents').status_code == 502
    assert not client.get(f'/api/sessions/{sid}').json()['documents']


def test_input_guards_and_origin(client):
    sid = create(client)['id']
    assert client.post(f'/api/sessions/{sid}/documents').status_code == 400
    assert chat(client, sid, '  ').status_code == 422
    assert client.post('/api/sessions', json={'scenario_id': 'unknown'}).status_code == 404
    assert client.get('/api/sessions/missing').status_code == 404
    assert client.get(f'/api/sessions/{sid}/documents/0/markdown').status_code == 404
    assert client.post('/api/sessions', headers={'Origin': 'https://evil.example'}, json={'scenario_id': 'aftersales', 'mode': 'demo'}).status_code == 403


def test_sessions_are_isolated(client):
    a, b = create(client)['id'], create(client)['id']
    chat(client, a)
    assert len(client.get(f'/api/sessions/{b}').json()['messages']) == 1
    assert len(client.get('/api/sessions').json()) == 2


def test_summary_agent_does_not_receive_hidden_facts(client, monkeypatch):
    session = create(client);session['mode'] = 'live'
    session['notes'] = [{'id': 'N1', 'category': '范围与边界', 'text': '自动退款'}]
    async def fake(system, messages, schema):
        assert 'facts' not in messages[0]['content']
        assert '50 个历史案例' not in messages[0]['content']
        return agents.Summary(overview='摘要', requirements=[agents.Requirement(section='范围与边界', text='自动退款', status='已确认', sources=['N1'])])
    monkeypatch.setattr(agents, 'completion', fake)
    draft = asyncio.run(agents.summarize(session, scenario_by_id('aftersales')))
    result = agents.validate_summary(draft, session['messages'], session['notes'])
    assert result['requirements'][0]['status'] == '待确认'


def test_invalid_evidence_is_rejected(client, monkeypatch):
    session = create(client); session['mode'] = 'live'
    async def fake(*args):
        return agents.Summary(overview='摘要', requirements=[agents.Requirement(section='范围与边界', text='虚构', status='已确认', sources=['M999'])])
    monkeypatch.setattr(agents, 'completion', fake)
    with pytest.raises(agents.AgentError):
        draft = asyncio.run(agents.summarize(session, scenario_by_id('aftersales')))
        agents.validate_summary(draft, session['messages'], session['notes'])


@pytest.mark.parametrize('scenario_id', [s['id'] for s in SCENARIOS])
def test_each_scenario_can_complete(client, scenario_id):
    session = client.post('/api/sessions', json={'scenario_id': scenario_id, 'mode': 'demo'}).json()
    assert chat(client, session['id'], '目标和用户是谁？').status_code == 200
    assert client.post(f"/api/sessions/{session['id']}/documents").status_code == 200


def test_catalog_contains_general_and_optional_local_scenarios(client):
    public = client.get('/api/bootstrap').json()['scenarios']
    assert {s['id'] for s in public} == {s['id'] for s in SCENARIOS}
    assert len([s for s in public if not s.get("business")]) == 4
    for case in public:
        assert 'facts' not in case
        sid = client.post('/api/sessions', json={'scenario_id':case['id'], 'mode':'demo'}).json()['id']
        chat(client, sid, '目标用户是谁？')
        doc = client.post(f'/api/sessions/{sid}/documents').json()['documents'][0]
        assert scenario_by_id(case['id'])['facts'][5][2] not in str(doc['result'])


def test_removed_scenario_history_stays_readable(client):
    s = create(client)
    s['scenario_id'] = 'retired_example'
    server.save(s)
    assert client.get(f"/api/sessions/{s['id']}").status_code == 200
    assert chat(client, s['id']).status_code == 409
    assert client.post(f"/api/sessions/{s['id']}/documents").status_code == 409



def test_delete_session_removes_its_data_only_and_is_retry_safe(client):
    sid, other = create(client)['id'], create(client)['id']
    chat(client, sid)
    client.post(f'/api/sessions/{sid}/notes', json={'text': '测试笔记', 'category': '目标与用户'})
    client.post(f'/api/sessions/{sid}/documents')
    assert client.delete(f'/api/sessions/{sid}').json() == {'id': sid, 'deleted': True}
    assert client.get(f'/api/sessions/{sid}').status_code == 404
    assert client.get(f'/api/sessions/{sid}/documents/1/markdown').status_code == 404
    assert client.post(f'/api/sessions/{sid}/documents').status_code == 404
    assert chat(client, sid, rid='after-delete').status_code == 404
    assert client.post(f'/api/sessions/{sid}/notes', json={'text': '不能恢复', 'category': '目标与用户'}).status_code == 404
    assert client.delete(f'/api/sessions/{sid}').json()['deleted'] is False
    assert [s['id'] for s in client.get('/api/sessions').json()] == [other]
    assert client.get(f'/api/sessions/{other}').status_code == 200


def test_delete_cannot_be_triggered_cross_origin(client):
    sid = create(client)['id']
    assert client.delete(f'/api/sessions/{sid}', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get(f'/api/sessions/{sid}').status_code == 200


def test_delete_waits_for_running_graph_and_prevents_resurrection(client, monkeypatch):
    sid = create(client)['id']
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(*args):
            started.set()
            await release.wait()
            return '模型测试回复'
        monkeypatch.setattr(agents, 'stakeholder', delayed)
        running = asyncio.create_task(server.chat(sid, server.ChatInput(content='谁使用？', request_id='race')))
        await started.wait()
        deleting = asyncio.create_task(server.delete_session(sid))
        await asyncio.sleep(0)
        assert not deleting.done()
        release.set()
        await running
        assert (await deleting)['deleted'] is True
    asyncio.run(asyncio.wait_for(exercise(), timeout=3))
    assert client.get(f'/api/sessions/{sid}').status_code == 404


def test_review_finalize_reopen_and_frozen_export(client):
    sid = create(client)['id']
    chat(client, sid)
    draft = client.post(f'/api/sessions/{sid}/documents').json()
    assert draft['phase'] == 'reviewing'
    assert draft['documents'][0]['status'] == 'draft'
    original_evidence = copy.deepcopy(draft['documents'][0]['evidence'])
    final = client.post(f'/api/sessions/{sid}/documents/1/finalize').json()
    assert final['phase'] == 'finalized'
    assert final['documents'][0]['status'] == 'final'
    assert final['documents'][0]['evidence'] == original_evidence
    exported = client.get(f'/api/sessions/{sid}/documents/1/markdown').text
    assert '已由练习者复核定稿' in exported
    assert client.post(f'/api/sessions/{sid}/documents/1/finalize').json() == final
    assert client.post(f'/api/sessions/{sid}/continue').json()['phase'] == 'clarifying'
    assert chat(client, sid, '验收标准是什么？', 'r2').status_code == 200
    assert client.post(f'/api/sessions/{sid}/documents/1/finalize').status_code == 409
    assert client.get(f'/api/sessions/{sid}/documents/1/markdown').text == exported
    next_doc = client.post(f'/api/sessions/{sid}/documents').json()
    assert len(next_doc['documents']) == 2
    assert next_doc['documents'][1]['status'] == 'draft'


def test_failed_chat_retry_after_reload_no_duplicate_question(client, monkeypatch):
    sid = create(client)['id']
    original = agents.stakeholder
    async def fail(*args):
        raise agents.AgentError('连接失败')
    monkeypatch.setattr(agents, 'stakeholder', fail)
    assert chat(client, sid).status_code == 502
    pending = client.get(f'/api/sessions/{sid}').json()
    assert pending['pending_chat']['request_id'] == 'r1'
    assert chat(client, sid, '另外一个问题', 'r2').status_code == 409
    assert client.post(f'/api/sessions/{sid}/documents').status_code in (400,409)
    monkeypatch.setattr(agents, 'stakeholder', original)
    restored = chat(client, sid).json()
    assert len(restored['messages']) == 3 and 'pending_chat' not in restored
    assert restored['revision'] == 1
    assert chat(client, sid).json() == restored


def test_sqlite_checkpoint_survives_new_graph_and_is_deleted(client):
    from graph import build_graph
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    sid = create(client)['id']
    chat(client, sid)
    client.post(f'/api/sessions/{sid}/documents')
    async def inspect():
        async with AsyncSqliteSaver.from_conn_string(str(server.DB)) as saver:
            graph = build_graph(saver)
            return await graph.aget_state({'configurable': {'thread_id':sid}})
    snapshot = asyncio.run(inspect())
    assert snapshot.next == ('human_review',)
    assert len(snapshot.values['session']['messages']) == 3
    assert snapshot.tasks[0].interrupts
    assert client.post(f'/api/sessions/{sid}/documents/1/finalize').status_code == 200
    assert asyncio.run(inspect()).next == ()
    client.delete(f'/api/sessions/{sid}')
    assert not asyncio.run(inspect()).values


def test_note_change_blocks_stale_finalization(client):
    sid = create(client)['id']; chat(client, sid)
    client.post(f'/api/sessions/{sid}/documents')
    note = client.post(f'/api/sessions/{sid}/notes', json={'text':'增加验收测试', 'category':'验收标准'}).json()
    assert note['last_run']['nodes'][-1]['id'] == 'record_notes'
    assert client.post(f'/api/sessions/{sid}/documents/1/finalize').status_code == 409
    result = client.post(f'/api/sessions/{sid}/documents').json()
    assert result['documents'][-1]['evidence']['notes'][0]['text'] == '增加验收测试'
