"""One durable graph: conversation, evidence, documents and human review."""
import copy
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

import agents
import storage
from scenarios import scenario_by_id
from schemas import AgentError


class AgentContext(TypedDict):
    scenario_id: str
    mode: Literal['live', 'demo']
    messages: list[dict]
    notes: list[dict]


class WorkflowState(TypedDict, total=False):
    session: dict
    action: str
    question: str
    request_id: str
    context: AgentContext
    brief: dict
    answer: str
    draft: dict
    summary: dict
    document: dict
    error: str
    trace: list[str]


class StakeholderInput(TypedDict):
    context: AgentContext
    question: str
    trace: list[str]


class AnalystInput(TypedDict):
    context: AgentContext
    brief: dict
    trace: list[str]


NODE_LABELS = {
    'clarification': '需求澄清子图', 'documentation': '文档生成子图',
    'initialize': '载入练习', 'await_user': '等待用户操作',
    'record_user': '记录用户问题', 'prepare_context': '读取对话与笔记',
    'stakeholder_agent': '需求方 Agent', 'validate_reply': '回复校验',
    'record_assistant': '记录需求方回复', 'record_notes': '保存需求笔记',
    'summary_agent': '总结 Agent', 'validate_evidence': '来源校验',
    'assemble_document': '生成需求文档与 Markdown', 'save_draft': '保存草稿',
    'human_review': '人工审阅：补充或定稿', 'save_final': '保存定稿',
    'continue_clarification': '继续澄清', 'save_failure': '保存失败与重试状态',
}


def step(state, node, **updates):
    return {'trace': state.get('trace', []) + [node], **updates}


def persist(state, config, node, session=None, **updates):
    session = copy.deepcopy(session or state['session'])
    output = step(state, node, session=session, **updates)
    session['last_run'] = public_trace(output, session['mode'])
    path = config.get('configurable', {}).get('db_path')
    if path:
        storage.save(Path(path), session)
    return output


def initialize(state, config):
    session = copy.deepcopy(state['session'])
    session.setdefault('phase', 'clarifying')
    session.setdefault('requests', [])
    return persist(state, config, 'initialize', session)


def accept_input(state, name):
    # Pure interrupt: no side effects before resume, since this node replays.
    payload = interrupt({'phase': state['session'].get('phase', 'clarifying'),
                         'actions': ['chat', 'notes', 'document', 'continue', 'finalize']})
    return {**payload, 'error': '', 'trace': [name]}


def await_user(state):
    return accept_input(state, 'await_user')


def human_review(state):
    return accept_input(state, 'human_review')


def route_action(state):
    return {'chat': 'clarification', 'notes': 'clarification', 'document': 'documentation',
            'finalize': 'save_final', 'continue': 'clarification'}[state['action']]


def record_user(state, config):
    session = copy.deepcopy(state['session'])
    if not session.get('pending_chat'):
        session['messages'].append({'id': f"M{len(session['messages'])+1}",
                                    'role': 'user', 'content': state['question']})
        session['revision'] += 1
        session['pending_chat'] = {'content': state['question'], 'request_id': state['request_id']}
    session['phase'] = 'clarifying'
    session.pop('last_error', None)
    return persist(state, config, 'record_user', session)


def prepare_context(state):
    session = state['session']
    scenario = scenario_by_id(session['scenario_id'])
    if not scenario:
        raise AgentError('练习场景不存在。')
    context = {k: copy.deepcopy(session[k]) for k in ('scenario_id', 'mode', 'messages', 'notes')}
    if state['action'] == 'chat':
        # stakeholder() appends the current question itself.
        context['messages'] = context['messages'][:-1]
    return step(state, 'prepare_context', context=context,
                brief={'title': scenario['title'], 'initial': scenario['initial']})


async def stakeholder_agent(state: StakeholderInput):
    try:
        answer = await agents.stakeholder(state['context'], scenario_by_id(state['context']['scenario_id']), state['question'])
        return step(state, 'stakeholder_agent', answer=answer)
    except AgentError as error:
        return step(state, 'stakeholder_agent', error=str(error))


def validate_reply(state):
    answer = state.get('answer')
    if not isinstance(answer, str) or not answer.strip():
        return step(state, 'validate_reply', error='需求方没有返回有效回复，问题已保存，请重试。')
    return step(state, 'validate_reply', answer=answer.strip())


def record_assistant(state, config):
    session = copy.deepcopy(state['session'])
    rid = state['request_id']
    if rid not in session.setdefault('requests', []):
        session['messages'].append({'id': f"M{len(session['messages'])+1}", 'role': 'assistant', 'content': state['answer']})
        session['requests'].append(rid)
    session.pop('pending_chat', None)
    session.pop('last_error', None)
    return persist(state, config, 'record_assistant', session)


def record_notes(state, config):
    session = copy.deepcopy(state['session'])
    session['phase'] = 'clarifying'
    return persist(state, config, 'record_notes', session)


async def summary_agent(state: AnalystInput):
    try:
        draft = await agents.summarize(state['context'], state['brief'])
        return step(state, 'summary_agent', draft=draft)
    except AgentError as error:
        return step(state, 'summary_agent', error=str(error))


def validate_evidence(state):
    try:
        summary = agents.validate_summary(state['draft'], state['context']['messages'], state['context']['notes'])
        return step(state, 'validate_evidence', summary=summary)
    except (ValidationError, AgentError) as error:
        message = str(error) if isinstance(error, AgentError) else '总结未通过结构校验，本次文档未保存，请重试。'
        return step(state, 'validate_evidence', error=message)


def assemble_document(state):
    session, context = state['session'], state['context']
    document = {'version': len(session['documents'])+1, 'created_at': storage.now(),
                'input_revision': session['revision'], 'result': state['summary'], 'status': 'draft',
                'evidence': copy.deepcopy({'messages': context['messages'], 'notes': context['notes']})}
    document['markdown'] = agents.markdown(session, document)
    return step(state, 'assemble_document', document=document)


def save_draft(state, config):
    session = copy.deepcopy(state['session'])
    document = state['document']
    if len(session['documents']) < document['version']:
        session['documents'].append(copy.deepcopy(document))
    session['phase'] = 'reviewing'
    session.pop('last_error', None)
    return persist(state, config, 'save_draft', session)


def save_final(state, config):
    session = copy.deepcopy(state['session'])
    document = session['documents'][-1]
    if document['input_revision'] != session['revision'] or session.get('pending_chat'):
        raise AgentError('草稿已经过期，请重新生成。')
    document['status'] = 'final'
    document['finalized_at'] = storage.now()
    document['markdown'] = agents.markdown(session, document)
    session['phase'] = 'finalized'
    return persist(state, config, 'save_final', session, document=document)


def continue_clarification(state, config):
    session = copy.deepcopy(state['session'])
    session['phase'] = 'clarifying'
    return persist(state, config, 'continue_clarification', session)


def save_failure(state, config):
    session = copy.deepcopy(state['session'])
    session['last_error'] = state['error']
    return persist(state, config, 'save_failure', session)


def add_nodes(builder, names):
    for name in names:
        kwargs = {'input_schema': StakeholderInput} if name == 'stakeholder_agent' else {'input_schema': AnalystInput} if name == 'summary_agent' else {}
        builder.add_node(name, globals()[name], **kwargs)


def checked_edge(builder, source, target):
    builder.add_conditional_edges(source, lambda s: 'save_failure' if s.get('error') else target,
                                  {target: target, 'save_failure': 'save_failure'})


def build_clarification_graph():
    """Chat and user notes share one subgraph and one session contract."""
    b = StateGraph(WorkflowState)
    add_nodes(b, ['record_user', 'prepare_context', 'stakeholder_agent', 'validate_reply',
                  'record_assistant', 'record_notes', 'continue_clarification', 'save_failure'])
    b.add_conditional_edges(START, lambda s: s['action'],
                            {'chat': 'record_user', 'notes': 'record_notes', 'continue': 'continue_clarification'})
    b.add_edge('record_user', 'prepare_context')
    b.add_edge('prepare_context', 'stakeholder_agent')
    checked_edge(b, 'stakeholder_agent', 'validate_reply')
    checked_edge(b, 'validate_reply', 'record_assistant')
    for node in ('record_assistant', 'record_notes', 'continue_clarification', 'save_failure'):
        b.add_edge(node, END)
    # Inherit the parent's checkpointer; each invocation gets its own namespace.
    return b.compile(name='clarification')


def build_document_graph():
    """Only actual dialogue and notes feed the document pipeline."""
    b = StateGraph(WorkflowState)
    add_nodes(b, ['prepare_context', 'summary_agent', 'validate_evidence',
                  'assemble_document', 'save_draft', 'save_failure'])
    b.add_edge(START, 'prepare_context')
    b.add_edge('prepare_context', 'summary_agent')
    checked_edge(b, 'summary_agent', 'validate_evidence')
    checked_edge(b, 'validate_evidence', 'assemble_document')
    b.add_edge('assemble_document', 'save_draft')
    b.add_edge('save_draft', END)
    b.add_edge('save_failure', END)
    return b.compile(name='documentation')


def build_graph(checkpointer=None):
    b = StateGraph(WorkflowState)
    add_nodes(b, ['initialize', 'await_user', 'human_review', 'save_final'])
    b.add_node('clarification', build_clarification_graph())
    b.add_node('documentation', build_document_graph())
    b.add_edge(START, 'initialize')
    b.add_edge('initialize', 'await_user')
    routes = {n:n for n in ('clarification', 'documentation', 'save_final')}
    for gate in ('await_user', 'human_review'):
        b.add_conditional_edges(gate, route_action, routes)
    b.add_edge('clarification', 'await_user')
    b.add_conditional_edges('documentation', lambda s: 'await_user' if s.get('error') else 'human_review',
                            {'await_user':'await_user', 'human_review':'human_review'})
    b.add_edge('save_final', END)
    return b.compile(checkpointer=checkpointer, name='requirement_practice')


workflow = build_graph()


def public_trace(output, mode):
    return {'engine':'LangGraph', 'mode':mode,
            'nodes':[{'id':n, 'label':NODE_LABELS[n]} for n in output['trace']]}


async def _run(saver, action, session, question, db_path, request_id):
    graph = build_graph(saver)
    config = {'configurable': {'thread_id':session['id'], 'db_path':str(db_path) if db_path else ''}, 'recursion_limit':30}
    snapshot = await graph.aget_state(config)
    if not snapshot.values or not snapshot.next:
        await graph.ainvoke({'session':copy.deepcopy(session), 'trace':[]}, config)
    if action == 'initialize':
        return (await graph.aget_state(config)).values
    payload = {'session':copy.deepcopy(session), 'action':action, 'question':question,
               'request_id':request_id or 'local-test'}
    snapshot = await graph.aget_state(config)
    if snapshot.next not in [('await_user',), ('human_review',)]:
        # Unexpected process interruption: finish the already checkpointed operation first.
        await graph.ainvoke(None, config)
        recovered = (await graph.aget_state(config)).values
        if recovered.get('action') == action and (action != 'chat' or recovered.get('request_id') == payload['request_id']):
            if recovered.get('error'): raise AgentError(recovered['error'])
            return recovered
        raise AgentError('上次中断的操作已恢复，请刷新页面后继续。')
    output = await graph.ainvoke(Command(resume=payload), config)
    if output.get('error'):
        raise AgentError(output['error'])
    return output


async def run_workflow(action, session, question='', *, db_path=None, request_id=''):
    if db_path:
        async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
            return await _run(saver, action, session, question, db_path, request_id)
    return await _run(InMemorySaver(), action, session, question, None, request_id)


async def delete_checkpoint(db_path, sid):
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()
        await saver.adelete_thread(sid)
