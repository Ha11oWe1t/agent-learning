const $ = id => document.getElementById(id);
const state = {boot:null, session:null, busy:false, edit:null, version:null, pendingChat:null, stage:1};
const el = (tag, cls, text) => { const node=document.createElement(tag); if(cls) node.className=cls; if(text!==undefined) node.textContent=text; return node; };
let toastTimer;
let pendingDelete=null;
function toast(message, error=false) { $('toast').textContent=message; $('toast').className=error?'error':''; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,error?10000:4000); }
async function api(path, method='GET', body) {
  const response=await fetch('/api'+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'输入不符合要求，请检查长度和内容。');
  return data;
}
function setBusy(value, label='正在处理…') {
  state.busy=value; $('busy-indicator').hidden=!value; $('busy-text').textContent=label;
  document.querySelectorAll('button:not([data-guide-control])').forEach(button=>button.disabled=value);
  $('mode').disabled=value; $('document-version').disabled=value;
  document.querySelectorAll('textarea').forEach(field=>field.readOnly=value);
  $('note-category').disabled=value;
}
async function operation(label, fn) {
  if(state.busy) return;
  setBusy(true,label);
  try {await fn();} catch(error) {if(state.session){try{state.session=await api('/sessions/'+state.session.id);renderSession();}catch{}}toast(error.message || '请求失败，请稍后重试。',true);} finally {setBusy(false);if(state.session)renderDocument();}
}
function scenario(){return state.boot.scenarios.find(s=>s.id===state.session.scenario_id)||{category:'历史练习',person:'需求方',role:'已下架场景',simulation_notice:'此场景已下架，历史记录仍可查看、导出或删除。请新建通用场景继续练习。'};}
function draftKey(){return 'agent-lab-draft-'+state.session.id;}
function storeDraft(){
  if(!state.session)return;
  try {localStorage.setItem(draftKey(),JSON.stringify({question:$('question').value,text:$('note-text').value,category:$('note-category').value,edit:state.edit}));$('draft-status').textContent='草稿已保存在浏览器';}
  catch {$('draft-status').textContent='浏览器无法保存草稿，请及时保存笔记';}
}
function restoreDraft(){
  let draft={};try {draft=JSON.parse(localStorage.getItem(draftKey())||'{}');}catch{}
  $('question').value=draft.question||'';$('note-text').value=draft.text||'';$('note-category').value=draft.category||state.boot.categories[0];
  state.edit=draft.edit&&state.session.notes.some(n=>n.id===draft.edit)?draft.edit:null;
  updateEditLabel();
}
function updateEditLabel(){$('save-note').textContent=state.edit?'保存修改':'＋ 保存笔记';$('cancel-edit').hidden=!state.edit;}
async function renderHistory(){
  const items=await api('/sessions');$('history-count').textContent=items.length;$('history').replaceChildren();
  if(!items.length)$('history').append(el('p','history-empty','还没有练习，选择一个需求开始吧。'));
  for(const item of items){const row=el('div','history-row'+(state.session?.id===item.id?' selected':''));const button=el('button','history-item');button.append(el('span','',item.title),el('small','',`${item.mode==='demo'?'演示':'模型'} · ${item.turns} 轮对话 · ${item.documents} 份文档`));button.onclick=()=>operation('正在恢复练习…',async()=>openSession(await api('/sessions/'+item.id)));button.disabled=state.busy;const remove=el('button','history-delete','删除');remove.setAttribute('aria-label','删除练习：'+item.title);remove.title='删除这次练习';remove.disabled=state.busy;remove.onclick=()=>{if(state.busy)return;pendingDelete=item;$('delete-description').textContent=`「${item.title}」 · ${item.mode==='demo'?'演示':'模型'} · ${item.turns} 轮对话 · ${item.documents} 份文档`;$('delete-dialog').showModal();};row.append(button,remove);$('history').append(row);}
}
$('delete-cancel').onclick=()=>$('delete-dialog').close();
$('delete-dialog').addEventListener('close',()=>{pendingDelete=null;});
$('delete-confirm').onclick=()=>{
  if(!pendingDelete||state.busy)return;
  const item=pendingDelete;$('delete-dialog').close();
  operation('正在删除练习…',async()=>{
    await api('/sessions/'+item.id,'DELETE');
    const isCurrent=state.session?.id===item.id;
    if(isCurrent){showStage(1);$('design-frame').removeAttribute('src');state.session=null;state.pendingChat=null;state.edit=null;state.version=null;$('question').value='';$('note-text').value='';updateEditLabel();$('workspace').hidden=true;$('home').hidden=false;}
    try{localStorage.removeItem('agent-lab-draft-'+item.id);if(localStorage.getItem('agent-lab-current')===item.id)localStorage.removeItem('agent-lab-current');}catch{}
    await renderHistory();toast('练习及其对话、笔记、文档已删除');
  });
};
function renderScenarios(){
  const icons=['♧','⌘','⚙','↗'];$('scenarios').replaceChildren();
  state.boot.scenarios.forEach((s,index)=>{const card=el('button','scenario '+s.color);card.setAttribute('aria-label','开始练习：'+s.title);const top=el('div','card-top');top.append(el('span','scenario-icon',s.icon||icons[index%icons.length]),el('span','badge',s.level+' · '+s.category));const footer=el('div','card-footer');footer.append(el('span','',s.duration+' / '+s.person),el('strong','','开始练习 ↗'));card.append(top,el('h3','',s.title),el('p','',s.description),footer);card.onclick=()=>operation('正在创建练习…',async()=>{await openSession(await api('/sessions','POST',{scenario_id:s.id,mode:$('mode').value}));});$('scenarios').append(card);});
}
async function openSession(session){
  if(state.session)storeDraft();
  state.session=session;state.pendingChat=null;state.version=session.documents.at(-1)?.version||null;
  $('home').hidden=true;$('workspace').hidden=false;
  try{localStorage.setItem('agent-lab-current',session.id);}catch{}
  restoreDraft();if(session.pending_chat){state.pendingChat=session.pending_chat;$('question').value=session.pending_chat.content;}renderSession();switchTab('notes');await renderHistory();if(state.stage===3)await showStage(3);
}
function renderSession(){
  const s=state.session, sc=scenario();$('session-title').textContent=s.title;$('session-category').textContent=sc.category+' / 需求澄清练习';
  $('session-meta').textContent=`${Math.floor((s.messages.length-1)/2)} 轮对话 · ${s.notes.length} 条笔记 · ${{clarifying:'澄清中',reviewing:'待人工审阅',finalized:'已定稿'}[s.phase]||'澄清中'}${s.pending_chat?' · 问题已保存，等待重试':''} · 已保存到本地`;
  $('demo-banner').hidden=s.mode!=='demo';$('person-name').textContent=sc.person;$('person-role').textContent=sc.role;$('person-avatar').textContent=sc.person[0];
  $('simulation-banner').hidden=!sc.simulation_notice;$('simulation-banner').textContent=sc.simulation_notice||'';
  $('key-banner').hidden=s.mode!=='live'||state.boot.model.ready;
  $('workflow-trace').hidden=!s.last_run;
  $('workflow-path').textContent=s.last_run?s.last_run.nodes.map(n=>n.label).join(' → '):'';
  renderMessages();renderNotes();renderDocument();
}
function renderMessages(){
  $('messages').replaceChildren();
  for(const message of state.session.messages){const box=el('div','message '+(message.role==='user'?'user':'assistant'));box.id='message-'+message.id;const label=el('div','message-label',`${message.role==='user'?'你 · 开发工程师':scenario().person+' · 需求方'} / ${message.id}`);
    const capture=el('button','capture','＋ 记笔记');capture.title='引用这条对话到笔记草稿';capture.onclick=()=>{switchTab('notes');$('note-text').value+=($('note-text').value?'\n\n':'')+`[${message.id}] ${message.content}`;storeDraft();$('note-text').focus();};label.append(capture);box.append(label,el('div','message-text',message.content));$('messages').append(box);}
  $('messages').scrollTop=$('messages').scrollHeight;
}
function renderNotes(){
  $('note-count').textContent=state.session.notes.length;$('notes-list').replaceChildren();
  if(!state.session.notes.length){const empty=el('div','empty');empty.append(el('p','','还没有保存的笔记。也可以点击对话旁的“记笔记”，引用原话。'));$('notes-list').append(empty);}
  for(const note of state.session.notes){const box=el('div','note');const head=el('div','note-head');head.append(el('span','',`${note.id} / ${note.category}`));const actions=el('div');const edit=el('button','','编辑');edit.onclick=()=>{state.edit=note.id;$('note-category').value=note.category;$('note-text').value=note.text;updateEditLabel();storeDraft();$('note-text').focus();};const remove=el('button','','删除');remove.onclick=()=>operation('正在删除笔记…',async()=>{state.session=await api(`/sessions/${state.session.id}/notes/${note.id}`,'DELETE');if(state.edit===note.id)resetNote();renderSession();toast('笔记已删除，已有文档证据快照保留');});actions.append(edit,remove);head.append(actions);box.append(head,el('p','',note.text));$('notes-list').append(box);}
}
function resetNote(){state.edit=null;$('note-text').value='';updateEditLabel();storeDraft();}
function switchTab(tab){
  const notes=tab==='notes';$('notes-pane').hidden=!notes;$('document-pane').hidden=notes;
  $('notes-tab').classList.toggle('selected',notes);$('document-tab').classList.toggle('selected',!notes);
  $('notes-tab').setAttribute('aria-selected',String(notes));$('document-tab').setAttribute('aria-selected',String(!notes));
}
function renderDocument(){
  const docs=state.session.documents;$('document-count').textContent=docs.length;$('document-empty').hidden=!!docs.length;$('document-content').hidden=!docs.length;
  if(!docs.length)return;
  const document=docs.find(d=>d.version===state.version)||docs.at(-1);state.version=document.version;
  $('document-version').replaceChildren(...docs.map(d=>{const option=el('option','',`v${d.version} · ${d.status==='final'?'已定稿':'草稿'}`);option.value=d.version;return option;}));$('document-version').value=document.version;
  $('download').href=`/api/sessions/${state.session.id}/documents/${document.version}/markdown`;
  $('stale-banner').hidden=document.input_revision===state.session.revision;
  const final=document.status==='final', stale=document.input_revision!==state.session.revision;
  $('enter-design').hidden=!final; $('enter-design').href=`/design?sid=${state.session.id}&version=${document.version}`;
  $('review-status').textContent=final?'已由你复核定稿 · 不代表真实需求方签字验收。':'待人工审阅 · 对照来源检查，待确认与冲突项仍会保留。';
  $('finalize-document').hidden=final;
  $('finalize-document').disabled=state.busy||stale||!!state.session.pending_chat||document.version!==docs.at(-1).version;

  const body=$('document-body');body.replaceChildren(el('h3','','访谈概况'),el('p','',document.result.overview));
  for(const section of state.boot.categories){body.append(el('h3','',section));const items=document.result.requirements.filter(r=>r.section===section);if(!items.length)body.append(el('p','','尚未澄清。'));
    for(const item of items){const row=el('div','requirement');row.append(el('span','status '+(item.status==='待确认'?'pending':item.status==='存在冲突'?'conflict':''),item.status),el('p','',item.text));const sources=el('div','sources');const evidence=el('div','evidence');evidence.hidden=true;
      item.sources.forEach(id=>{const button=el('button','',id+' ↗');button.title='查看生成时的来源快照';button.onclick=()=>{const source=[...document.evidence.messages,...document.evidence.notes].find(s=>s.id===id);evidence.textContent=id+' · '+(source?.content||source?.text||'来源不可用');evidence.hidden=false;};sources.append(button);});row.append(sources,evidence);body.append(row);}}
  body.append(el('h3','','下一步可以继续追问'));if(!document.result.questions.length)body.append(el('p','','暂无额外追问建议，请人工复核需求完整性。'));document.result.questions.forEach(q=>body.append(el('p','','• '+q)));
}
$('new-practice').onclick=()=>{showStage(1);if(state.session)storeDraft();state.session=null;$('home').hidden=false;$('workspace').hidden=true;try{localStorage.removeItem('agent-lab-current');}catch{}renderHistory().catch(e=>toast(e.message,true));};
$('notes-tab').onclick=()=>switchTab('notes');$('document-tab').onclick=()=>switchTab('document');$('cancel-edit').onclick=resetNote;
$('document-version').onchange=()=>{state.version=Number($('document-version').value);renderDocument();};
$('question').addEventListener('input',storeDraft);$('note-text').addEventListener('input',storeDraft);$('note-category').addEventListener('change',storeDraft);
$('question').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!state.busy)$('chat-form').requestSubmit();}});
$('chat-form').onsubmit=event=>{event.preventDefault();const text=$('question').value.trim();if(!text||!state.session)return;
  operation('需求方正在回复，请稍候…',async()=>{
    if(!state.pendingChat||state.pendingChat.content!==text)state.pendingChat={content:text,request_id:crypto.randomUUID()};
    state.session=await api(`/sessions/${state.session.id}/messages`,'POST',state.pendingChat);state.pendingChat=null;
    if($('question').value.trim()===text)$('question').value='';storeDraft();renderSession();await renderHistory();$('question').focus();
  });};
async function saveNote(){
  const text=$('note-text').value.trim();if(!text)return;
  const path=`/sessions/${state.session.id}/notes`+(state.edit?'/'+state.edit:'');
  state.session=await api(path,state.edit?'PUT':'POST',{text,category:$('note-category').value});resetNote();renderSession();
}
$('note-form').onsubmit=event=>{event.preventDefault();operation('正在保存笔记…',async()=>{await saveNote();toast('笔记已保存');});};
$('generate').onclick=()=>operation('总结 Agent 正在整理需求与证据…',async()=>{
  if($('note-text').value.trim())await saveNote();
  state.session=await api(`/sessions/${state.session.id}/documents`,'POST');state.version=state.session.documents.at(-1).version;renderSession();switchTab('document');await renderHistory();toast('需求文档已生成，请复核已确认与待确认事项');
});
$('finalize-document').onclick=()=>operation('正在保存定稿…',async()=>{
  if($('note-text').value.trim()||$('question').value.trim()){toast('请先保存笔记或发送问题，再生成包含这些内容的新草稿。',true);return;}
  state.session=await api(`/sessions/${state.session.id}/documents/${state.version}/finalize`,'POST');renderSession();await renderHistory();toast('已复核定稿，可导出 Markdown');
});
$('continue-document').onclick=()=>operation('返回需求澄清…',async()=>{
  state.session=await api(`/sessions/${state.session.id}/continue`,'POST');renderSession();switchTab('notes');$('question').focus();
});
window.addEventListener('beforeunload',storeDraft);
async function init(){
  try{state.boot=await api('/bootstrap');$('model-status').textContent=state.boot.model.ready?`○ ${state.boot.model.name} · 配置存在，连接未验证`:`○ ${state.boot.model.name} · 待填写 API Key`;
    $('model-status').title=state.boot.model.source+'；API 标识：'+state.boot.model.api_model+'；真实对话会调用 DeepSeek，产生 API 用量';
    $('mode').value=state.boot.model.ready?'live':'demo';
    if(!state.boot.model.ready)$('mode').options[0].disabled=true;
    $('note-category').replaceChildren(...state.boot.categories.map(c=>{const option=el('option','',c);option.value=c;return option;}));
    renderScenarios();await renderHistory();let id;try{id=localStorage.getItem('agent-lab-current');}catch{}
    if(id){try{await openSession(await api('/sessions/'+id));}catch{toast('上次练习未能恢复，请从记录中选择或新建练习。',true);}}
  }catch(error){$('model-status').textContent='服务连接失败';toast(error.message,true);}
}
init();

async function showStage(stage, chosenVersion=null){
  state.stage=stage;
  $('mobile-stage-select').value=String(stage);
  $('home').hidden=stage===3||!!state.session;
  $('workspace').hidden=stage===3||!state.session;
  $('design-workspace').hidden=stage!==3;
  $('stage-clarify').classList.toggle('active',stage===1);
  $('stage-design').classList.toggle('active',stage===3);
  $('stage-clarify').setAttribute('aria-current',stage===1?'step':'false');
  $('stage-design').setAttribute('aria-current',stage===3?'step':'false');
  document.querySelector('.topbar .eyebrow').textContent=stage===1?'LANGGRAPH / 01':'LANGGRAPH / 03';
  document.querySelector('.top-title').textContent=stage===1?'需求澄清':'技术方案设计';
  document.querySelector('.guide-entry').dataset.stageGuide=String(stage);
  if(stage!==3){if(state.session)renderSession();return;}
  if(state.session)storeDraft();
  const sid=state.session?.id;
  if(sid){try{const latest=await api('/sessions/'+sid);if(state.stage!==3||state.session?.id!==sid)return;state.session=latest;}catch(e){toast(e.message,true);return;}}
  const previous=$('design-frame').getAttribute('src');
  if(!chosenVersion&&previous){const q=new URL(previous,location.origin).searchParams;if(q.get('sid')===sid)chosenVersion=Number(q.get('version'));}
  const doc=state.session?.documents.find(d=>d.version===chosenVersion&&d.status==='final')||state.session?.documents.filter(d=>d.status==='final').at(-1);
  $('design-prerequisite').hidden=!!doc;
  $('design-frame').hidden=!doc;
  if(!doc){$('design-prerequisite-text').textContent=state.session?`当前练习「${state.session.title}」还没有已定稿的需求文档。请先生成需求文档并复核定稿，然后从左侧继续进入本阶段。`:'请先从左侧最近练习选择一个练习，或在需求澄清阶段开始新的练习。技术方案会关联这次练习的已定稿需求文档。';return;}
  const src=`/design?embedded=1&sid=${state.session.id}&version=${doc.version}`;
  if($('design-frame').getAttribute('src')!==src)$('design-frame').src=src;
}
$('stage-clarify').onclick=()=>showStage(1);
$('stage-design').onclick=()=>showStage(3);
$('mobile-stage-select').onchange=()=>showStage(Number($('mobile-stage-select').value));
$('return-clarify').onclick=()=>{showStage(1);if(state.session)switchTab('document');};
$('enter-design').onclick=e=>{e.preventDefault();showStage(3,state.version);};
window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===$('design-frame').contentWindow&&event.data?.type==='return-clarification'){showStage(1);if(state.session)switchTab('document');}});
