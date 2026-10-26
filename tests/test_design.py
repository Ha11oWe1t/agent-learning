import copy
import pytest
from fastapi.testclient import TestClient
import app
import design
from schemas import AgentError

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'DB',tmp_path/'design.sqlite3');app.locks.clear()
    with TestClient(app.app) as c:yield c

def ready(c):
    s=c.post('/api/sessions',json={'scenario_id':'aftersales','mode':'demo'}).json();sid=s['id']
    c.post(f'/api/sessions/{sid}/messages',json={'content':'目标用户是谁？','request_id':'one'})
    c.post(f'/api/sessions/{sid}/documents');c.post(f'/api/sessions/{sid}/documents/1/finalize')
    path=f'/api/sessions/{sid}/designs/1'
    return sid,path,c.post(path).json()['design']

def body(d):return {k:d[k] for k in ('revision','nodes','edges','decisions')}

def test_design_requires_final_document(client):
    sid=client.post('/api/sessions',json={'scenario_id':'itdesk','mode':'demo'}).json()['id']
    assert client.post(f'/api/sessions/{sid}/designs/1').status_code==404
    client.post(f'/api/sessions/{sid}/messages',json={'content':'谁使用？','request_id':'q'})
    client.post(f'/api/sessions/{sid}/documents')
    assert client.post(f'/api/sessions/{sid}/designs/1').status_code==409

def test_save_review_export_restore_and_delete(client):
    sid,path,d=ready(client)
    node=copy.deepcopy(d['nodes'][0]);node.update(id='collect',title='收集信息',executor='模型',agent='访谈 Agent',rationale='理解自由描述')
    d['nodes'].append(node);d['edges']=[{'source':'start','target':'collect','condition':''},{'source':'collect','target':'collect','condition':'信息不足'},{'source':'collect','target':'end','condition':'信息完整'}]
    saved=client.put(path,json=body(d));assert saved.status_code==200
    saved=saved.json();assert saved['revision']==1
    assert client.put(path,json=body(d)).status_code==409
    assert client.post(path).json()['design']==saved
    req={'revision':1,'node_id':'collect','question':'这个步骤还有什么遗漏？','request_id':'review1'}
    reviewed=client.post(path+'/reviews',json=req).json()
    assert reviewed['nodes']==saved['nodes']
    assert reviewed['reviews'][0]['trace']==['结构检查','技术负责人 Agent']
    assert reviewed['reviews'][0]['result']['findings'][0]['node_id']=='collect'
    assert len(client.post(path+'/reviews',json=req).json()['reviews'])==1
    assert '访谈 Agent' in client.get(path+'/markdown').text
    assert client.post(f'/api/sessions/{sid}/continue').status_code==200
    assert client.post(path).json()['design']==reviewed
    client.delete(f'/api/sessions/{sid}')
    assert client.post(path).status_code==404
    with app.database() as conn:assert conn.execute('SELECT count(*) FROM designs').fetchone()[0]==0

def test_invalid_links_and_revision_are_rejected(client):
    _,path,d=ready(client)
    bad=body(d);bad['edges']=[{'source':'start','target':'missing','condition':''}]
    assert client.put(path,json=bad).status_code==422
    bad=body(d);bad['nodes']=bad['nodes'][:1]
    assert client.put(path,json=bad).status_code==422
    assert client.post(path+'/reviews',json={'revision':3,'request_id':'r'}).status_code==409
    assert client.post(path+'/reviews',json={'revision':0,'node_id':'missing','request_id':'r'}).status_code==422

def test_live_review_uses_only_visible_requirement_and_design(client,monkeypatch):
    sid,path,d=ready(client);s=app.load(sid);s['mode']='live';app.save(s)
    async def fake(system,messages,schema):
        text=messages[0]['content'];assert 'facts' not in text
        assert '开始' in text and '本次讨论' in text
        return schema(reply='为什么选择单 Agent？',findings=[])
    monkeypatch.setattr(design,'completion',fake)
    assert client.post(path+'/reviews',json={'revision':0,'request_id':'r'}).status_code==200
    async def fail(*args):raise AgentError('模型连接失败')
    monkeypatch.setattr(design,'completion',fail)
    assert client.post(path+'/reviews',json={'revision':0,'request_id':'r2'}).status_code==502
    assert len(client.post(path).json()['design']['reviews'])==1
    assert client.put(path,json=body(d),headers={'origin':'https://outside.example'}).status_code==403
