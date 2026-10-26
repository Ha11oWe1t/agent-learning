import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents import markdown
from models import config
from schemas import AgentError, SECTIONS
from graph import run_workflow, delete_checkpoint
from scenarios import SCENARIOS, public_scenario, scenario_by_id

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv("PRACTICE_DB", str(ROOT / "data" / "practice.sqlite3")))
app = FastAPI(title="Agent 实战练习室", docs_url=None, redoc_url=None)
locks = {}


from storage import now
import storage

def database():
    return storage.database(DB)

def load(sid):
    return storage.load(DB, sid)

def save(session):
    storage.save(DB, session)


def session_lock(sid):
    return locks.setdefault(sid, asyncio.Lock())


@app.middleware("http")
async def same_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        origin = request.headers.get("origin")
        if (origin and origin.rstrip("/") != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "请从本地练习页面发起操作"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'"
    return response


@app.exception_handler(AgentError)
async def model_error(request, error):
    return JSONResponse({"detail": str(error)}, status_code=502)


class NewSession(BaseModel):
    scenario_id: str
    mode: Literal["live", "demo"] = "live"


class ChatInput(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=1, max_length=80)


class NoteInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    category: Literal["目标与用户", "范围与边界", "流程与确认", "数据与依赖", "权限与异常", "验收标准", "排期与约束"]


@app.get("/api/bootstrap")
def bootstrap():
    settings = config()
    return {"scenarios": [public_scenario(s) for s in SCENARIOS], "categories": SECTIONS,
            "engine": "LangGraph",
            "model": {"ready": bool(settings["key"]), "name": settings["label"],
                      "api_model": settings["model"], "source": settings["source"]}}


@app.get("/api/sessions")
def sessions():
    with database() as conn:
        rows = [json.loads(r[0]) for r in conn.execute("SELECT body FROM sessions").fetchall()]
    return [{k: s[k] for k in ("id", "title", "scenario_id", "mode", "updated_at", "revision")} |
            {"turns": (len(s["messages"]) - 1) // 2, "documents": len(s["documents"])}
            for s in sorted(rows, key=lambda x: x["updated_at"], reverse=True)]


@app.post("/api/sessions")
async def create_session(body: NewSession):
    scenario = scenario_by_id(body.scenario_id)
    if not scenario:
        raise HTTPException(404, "未找到这个需求场景")
    if body.mode == "live" and not config()["key"]:
        raise HTTPException(400, "请先在本项目 .env 填写 DEEPSEEK_API_KEY，或选择离线演示模式")
    session = {"id": uuid4().hex, "scenario_id": scenario["id"], "title": scenario["title"], "mode": body.mode,
               "revision": 0, "created_at": now(), "updated_at": now(), "notes": [], "note_counter": 0,
               "messages": [{"id": "M1", "role": "assistant", "content": scenario["initial"]}], "documents": [], "requests": []}
    return (await run_workflow("initialize", session, db_path=DB))["session"]


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    return load(sid)


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str):
    # Share the write lock with graph runs: a late reply cannot recreate the row.
    # Keep the lock registered, since already waiting requests may reference it.
    async with session_lock(sid):
        with database() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
            deleted = cursor.rowcount > 0
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='designs'").fetchone():
                conn.execute("DELETE FROM designs WHERE sid=?", (sid,))
        await delete_checkpoint(DB, sid)
    return {"id": sid, "deleted": deleted}


@app.post("/api/sessions/{sid}/messages")
async def chat(sid: str, body: ChatInput):
    if not body.content.strip():
        raise HTTPException(422, "请输入具体问题")
    async with session_lock(sid):
        session = load(sid)
        if not scenario_by_id(session["scenario_id"]):
            raise HTTPException(409, "此场景已下架，请新建通用场景练习；历史记录仍保留。")
        if body.request_id in session["requests"]:
            return session
        if len(session["messages"]) >= 101:
            raise HTTPException(400, "本次练习已达到 50 轮上限，请生成文档或新建练习")
        pending = session.get("pending_chat")
        if pending and (pending["request_id"] != body.request_id or pending["content"] != body.content.strip()):
            raise HTTPException(409, "上一条问题已保存，请先重试该问题，再继续提问。")
        return (await run_workflow("chat", session, body.content.strip(), db_path=DB,
                                   request_id=body.request_id))["session"]


@app.post("/api/sessions/{sid}/notes")
async def add_note(sid: str, body: NoteInput):
    async with session_lock(sid):
        session = load(sid)
        if len(session["notes"]) >= 60 or not body.text.strip():
            raise HTTPException(400, "笔记不能为空，每次练习最多 60 条")
        session["note_counter"] += 1
        session["notes"].append({"id": f"N{session['note_counter']}", "text": body.text.strip(), "category": body.category})
        session["revision"] += 1
        return (await run_workflow("notes", session, db_path=DB))["session"]


@app.put("/api/sessions/{sid}/notes/{nid}")
async def edit_note(sid: str, nid: str, body: NoteInput):
    async with session_lock(sid):
        session = load(sid)
        note = next((n for n in session["notes"] if n["id"] == nid), None)
        if not note:
            raise HTTPException(404, "笔记不存在")
        if not body.text.strip():
            raise HTTPException(422, "笔记不能为空")
        note.update(text=body.text.strip(), category=body.category)
        session["revision"] += 1
        return (await run_workflow("notes", session, db_path=DB))["session"]


@app.delete("/api/sessions/{sid}/notes/{nid}")
async def delete_note(sid: str, nid: str):
    async with session_lock(sid):
        session = load(sid)
        if not any(n["id"] == nid for n in session["notes"]):
            raise HTTPException(404, "笔记不存在")
        session["notes"] = [n for n in session["notes"] if n["id"] != nid]
        session["revision"] += 1
        return (await run_workflow("notes", session, db_path=DB))["session"]


@app.post("/api/sessions/{sid}/documents")
async def generate(sid: str):
    async with session_lock(sid):
        session = load(sid)
        if not scenario_by_id(session["scenario_id"]):
            raise HTTPException(409, "此场景已下架，请新建通用场景练习；已有文档仍可导出。")
        if len(session["messages"]) < 3:
            raise HTTPException(400, "请先与需求方完成至少一轮澄清，再生成需求文档")
        if session["documents"] and session["documents"][-1]["input_revision"] == session["revision"]:
            return session
        if session.get("pending_chat"):
            raise HTTPException(409, "请先重试未完成的对话，再生成文档。")
        return (await run_workflow("document", session, db_path=DB))["session"]


@app.post("/api/sessions/{sid}/documents/{version}/finalize")
async def finalize(sid: str, version: int):
    async with session_lock(sid):
        session = load(sid)
        if version < 1 or version != len(session["documents"]):
            raise HTTPException(409, "只能确认最新版本的需求文档。")
        document = session["documents"][-1]
        if document["input_revision"] != session["revision"] or session.get("pending_chat"):
            raise HTTPException(409, "对话或笔记已变化，请重新生成草稿再定稿。")
        if document.get("status") == "final":
            return session
        return (await run_workflow("finalize", session, db_path=DB))["session"]


@app.post("/api/sessions/{sid}/continue")
async def continue_practice(sid: str):
    async with session_lock(sid):
        return (await run_workflow("continue", load(sid), db_path=DB))["session"]


@app.get("/api/sessions/{sid}/documents/{version}/markdown")
def download(sid: str, version: int):
    session = load(sid)
    if version < 1 or version > len(session["documents"]):
        raise HTTPException(404, "文档版本不存在")
    document = session["documents"][version - 1]
    return Response(document.get("markdown") or markdown(session, document), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="requirements-v{version}.md"'})


from design import DesignInput, ReviewInput, review_graph, export_design


def design_source(sid, version):
    session = load(sid)
    if version < 1 or version > len(session['documents']):
        raise HTTPException(404, '需求文档不存在')
    doc = session['documents'][version-1]
    if doc.get('status') != 'final':
        raise HTTPException(409, '请先复核并定稿需求文档，再开始技术方案设计')
    return session, doc


def design_read(sid, version):
    with database() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS designs (sid TEXT, version INTEGER, body TEXT NOT NULL, PRIMARY KEY(sid,version))')
        row=conn.execute('SELECT body FROM designs WHERE sid=? AND version=?',(sid,version)).fetchone()
    return json.loads(row[0]) if row else None


def design_save(sid, version, data):
    with database() as conn:
        conn.execute('INSERT OR REPLACE INTO designs VALUES (?,?,?)',(sid,version,json.dumps(data,ensure_ascii=False)))


@app.post('/api/sessions/{sid}/designs/{version}')
async def start_design(sid: str, version: int):
    async with session_lock(sid):
        session,doc=design_source(sid,version)
        d=design_read(sid,version)
        if d is None:
            d={'revision':0,'nodes':[{'id':'start','title':'开始','x':80,'y':80},{'id':'end','title':'结束','x':550,'y':320}], 'edges':[], 'decisions':''}
            d=DesignInput.model_validate(d).model_dump() | {'reviews':[]}
            design_save(sid,version,d)
        return {'design':d,'requirement':doc,'title':session['title'],'mode':session['mode'],
                'source_stale':doc['input_revision']!=session['revision']}


@app.put('/api/sessions/{sid}/designs/{version}')
async def update_design(sid: str, version: int, body: DesignInput):
    async with session_lock(sid):
        design_source(sid,version)
        old=design_read(sid,version)
        if old is None: raise HTTPException(404,'请先开始设计')
        if old['revision']!=body.revision: raise HTTPException(409,'方案已在其他页面更新，请刷新；当前未保存内容可先导出本地草稿')
        d=body.model_dump() | {'revision':old['revision']+1,'reviews':old['reviews']}
        design_save(sid,version,d)
        return d


@app.post('/api/sessions/{sid}/designs/{version}/reviews')
async def review_design(sid: str, version: int, body: ReviewInput):
    async with session_lock(sid):
        session,doc=design_source(sid,version);d=design_read(sid,version)
        if d is None: raise HTTPException(404,'请先开始设计')
        if any(r['request_id']==body.request_id for r in d['reviews']): return d
        if d['revision']!=body.revision: raise HTTPException(409,'方案已变化，请保存最新方案再评审')
        if body.node_id and body.node_id not in {n['id'] for n in d['nodes']}: raise HTTPException(422,'节点不存在')
        if len(d['reviews'])>=60: raise HTTPException(400,'本方案已达到60轮评审上限')
        out=await review_graph.ainvoke({'design':{k:v for k,v in d.items() if k!='reviews'} | {'reviews':d['reviews'][-8:]},'requirement':doc,'request':body.model_dump(),'mode':session['mode']})
        d['reviews'].append(body.model_dump() | {'mode':session['mode'],'created_at':now(),'result':out['result'],'trace':out['trace']})
        design_save(sid,version,d)
        return d


@app.get('/api/sessions/{sid}/designs/{version}/markdown')
def download_design(sid: str, version: int):
    session,doc=design_source(sid,version);d=design_read(sid,version)
    if d is None: raise HTTPException(404,'方案不存在')
    return Response(export_design(session,doc,d),media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="design-v{version}.md"'})


@app.get('/design')
def design_page():
    return FileResponse(ROOT / 'web' / 'design.html')


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
