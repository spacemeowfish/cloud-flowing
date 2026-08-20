"use strict";

const appMode = document.body.dataset.mode || "user";

const API = {
  async request(path, options = {}) {
    const started = performance.now();
    const headers = {...(options.headers || {})};
    if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {...options, headers});
    const type = response.headers.get("content-type") || "";
    let body;
    if (type.includes("json")) body = await response.json();
    else body = await response.text();
    if (!response.ok) {
      const error = new Error(body?.message || body?.detail || `请求失败 (${response.status})`);
      error.status = response.status; error.body = body; throw error;
    }
    return {body, status: response.status, elapsed: Math.round(performance.now() - started)};
  },
  async get(path) { return (await this.request(path)).body; },
  async post(path, body) { return (await this.request(path, {method:"POST", body:JSON.stringify(body)})).body; },
  async put(path, body) { return (await this.request(path, {method:"PUT", body:JSON.stringify(body)})).body; }
};

const state = {
  capabilities:null, openapi:null, health:null, history:[], currentTask:null,
  eventSources:new Map(), inspectorTab:"response", apiChecks:[],
  speechByTask:new Map(), speechAudio:new Audio(), speechTaskId:null,
  desktopSettings:null, voiceStatus:null, voiceDevices:[], voiceRecording:null, voicePoll:null, voiceAutoStop:null, voiceStartPromise:null, voiceStopRequested:false, voiceCancelRequested:false
};

const lifecycle = ["接收","理解","校验","权限","路由","执行","交付"];
const stateMeta = {
  received:["已接收",0,""], understanding:["理解意图",1,""], validating:["校验参数",2,""],
  awaiting_confirmation:["等待确认",3,"warn"], waiting_network:["等待网络",4,"warn"], executing:["正在执行",5,""],
  delivering:["准备交付",6,""], completed:["已完成",7,"ok"], failed:["失败",0,"bad"], cancelled:["已取消",0,"bad"]
};
const terminal = new Set(["completed","failed","cancelled"]);
const routeInfo = {
  overview:["OPERATIONS","总览"], console:["UNIVERSAL TASK","通用任务"], knowledge:["KNOWLEDGE · R0 / D2","知识库问答"],
  files:["FILES · R1 / D1","文件查找"], reminders:["REMINDERS · R1 / D1","提醒管理"], todos:["TODOS · R1 / D1","待办事项"],
  schedule:["SCHEDULE · R1 / D1","日程管理"], text:["TEXT · R1 / D1","文本处理"], meetings:["MEETING · R2 / D2","会议纪要"],
  "api-lab":["CONTRACT LAB","接口测试中心"], tasks:["TASK LEDGER","任务历史"],
  settings:["DESKTOP SETTINGS","设置"], logs:["RECENT LOGS","最近日志"]
};
const toolLabels = {
  file_open:["文件查找","查找、候选选择、确认打开"], knowledge_query:["知识库问答","本地文档检索与来源引用"],
  general_chat:["通用问答","数学、常识、闲聊与翻译"],
  reminder_create:["提醒管理","创建、查询、取消、完成、清空"], todo_manage:["待办事项","创建、查询、更新、完成、删除"],
  schedule_manage:["日程管理","创建、范围查询、重复日程、取消"], text_polish:["文本处理","润色、总结、语气调整、草拟"],
  meeting_process:["会议纪要","授权文稿处理与 Markdown 输出"]
};

const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pretty = value => JSON.stringify(value ?? {}, null, 2);
const shortId = id => String(id || "").slice(0,8);
const fmt = value => value ? new Date(value).toLocaleString("zh-CN", {hour12:false, month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit"}) : "—";
const pageRoot = $("#pageRoot");

function toast(message, error=false) {
  const node = document.createElement("div"); node.className = `toast${error ? " error" : ""}`; node.textContent = message;
  $("#toastRegion").append(node); setTimeout(() => node.remove(), 3600);
}
function header(eyebrow, title, description, actions="") {
  return `<header class="page-header"><div><span class="eyebrow">${esc(eyebrow)}</span><h2>${esc(title)}</h2><p>${esc(description)}</p></div>${actions ? `<div class="page-actions">${actions}</div>` : ""}</header>`;
}
function rail(task=null) {
  const meta = task ? (stateMeta[task.state] || [task.state,0,""]) : ["",0,""];
  return `<div class="execution-rail">${lifecycle.map((name,index) => {
    const done = task && (task.state === "completed" || index < meta[1]);
    const current = task && !terminal.has(task.state) && index === meta[1];
    return `<div class="rail-step ${done ? "done" : current ? "current" : ""}"><b>0${index+1}</b><span>${name}</span></div>`;
  }).join("")}</div>`;
}
function subfeatures(items) {
  return `<div class="subfeature-grid">${items.map(([name,desc]) => `<div class="subfeature"><b>${esc(name)}</b><small>${esc(desc)}</small></div>`).join("")}</div>`;
}
function field(id,label,type="text",placeholder="",extra="") {
  if (type === "textarea") return `<div class="field ${extra}"><label for="${id}">${label}</label><textarea class="textarea" id="${id}" placeholder="${esc(placeholder)}"></textarea></div>`;
  return `<div class="field ${extra}"><label for="${id}">${label}</label><input class="input" id="${id}" type="${type}" placeholder="${esc(placeholder)}"></div>`;
}
function selectField(id,label,options,extra="") {
  return `<div class="field ${extra}"><label for="${id}">${label}</label><select class="select" id="${id}">${options.map(([v,l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select></div>`;
}
function panel(title, subtitle, body, extra="") {
  return `<section class="panel ${extra}"><header class="panel-head"><div><h3>${title}</h3>${subtitle ? `<p>${subtitle}</p>` : ""}</div></header><div class="panel-body">${body}</div></section>`;
}
function presets(values, target) {
  return `<div class="presets">${values.map(v => `<button class="preset" type="button" data-preset-target="${target}" data-preset="${esc(v)}">${esc(v)}</button>`).join("")}</div>`;
}
function bindPresets() {
  $$('[data-preset-target]').forEach(button => button.onclick = () => {
    const input = document.getElementById(button.dataset.presetTarget); if (input) { input.value = button.dataset.preset; input.focus(); }
  });
}
function bindTabs(container, callback) {
  $$(".segmented button", container).forEach(button => button.onclick = () => {
    $$(".segmented button", container).forEach(item => item.classList.toggle("active", item === button)); callback(button.dataset.action);
  });
}

function isLocked(name) { return state.desktopSettings?.locked_fields?.includes(name); }
function lockHint(name) { return isLocked(name) ? `<small class="locked-hint">由外部环境变量锁定</small>` : ""; }
function settingsInput(name,label,value,type="text",extra="") {
  const locked=isLocked(name); return `<div class="field ${extra}"><label for="set-${name}">${esc(label)}</label><input class="input" id="set-${name}" data-setting="${name}" type="${type}" value="${esc(value ?? "")}" ${locked?"disabled":""}>${lockHint(name)}</div>`;
}
function settingsTextarea(name,label,value,extra="") {
  const locked=isLocked(name); return `<div class="field ${extra}"><label for="set-${name}">${esc(label)}</label><textarea class="textarea compact-textarea" id="set-${name}" data-setting="${name}" ${locked?"disabled":""}>${esc(value ?? "")}</textarea>${lockHint(name)}</div>`;
}
function settingsToggle(name,label,checked) {
  const locked=isLocked(name); return `<label class="toggle-row"><input id="set-${name}" data-setting="${name}" type="checkbox" ${checked?"checked":""} ${locked?"disabled":""}><span>${esc(label)}</span>${lockHint(name)}</label>`;
}
function settingsSelect(name,label,value,options,extra="") {
  const locked=isLocked(name); return `<div class="field ${extra}"><label for="set-${name}">${esc(label)}</label><select class="select" id="set-${name}" data-setting="${name}" ${locked?"disabled":""}>${options.map(([id,text,disabled])=>`<option value="${esc(id)}" ${id===value?"selected":""} ${disabled?"disabled":""}>${esc(text)}</option>`).join("")}</select>${lockHint(name)}</div>`;
}

async function loadRuntime() {
  const capabilityPath = appMode === "developer" ? "/meta/capabilities" : "/meta/client-capabilities";
  const requests = [API.get("/health"), API.get(capabilityPath), API.get("/tasks?limit=100")];
  if (appMode === "developer") requests.push(API.get("/openapi.json"));
  const results = await Promise.allSettled(requests);
  if (results[0].status === "fulfilled") state.health = results[0].value;
  if (results[1].status === "fulfilled") state.capabilities = results[1].value;
  if (results[2].status === "fulfilled") state.history = results[2].value;
  if (appMode === "developer" && results[3]?.status === "fulfilled") state.openapi = results[3].value;
  state.voiceStatus = state.capabilities?.voice || state.voiceStatus;
  const ok = Boolean(state.health && state.capabilities);
  const sideDot = $("#sideHealthDot"), sideText = $("#sideHealthText"), badge = $("#runtimeBadge");
  if (sideDot) sideDot.className = `status-dot ${ok ? "ok" : "bad"}`;
  if (sideText) sideText.textContent = ok ? `服务在线 · ${state.health.model_provider}` : "服务不可用";
  if (badge) {
    badge.className = `runtime-badge ${ok ? "ok" : "bad"}`;
    const detail = appMode === "developer" ? `${state.health?.model_provider} · ${state.capabilities?.tools?.length || 0} tools` : "服务在线";
    badge.innerHTML = `<i></i>${ok ? detail : "服务离线"}`;
  }
}

function capabilityRows() {
  const routes = {file_open:"files",general_chat:"console",knowledge_query:"knowledge",reminder_create:"reminders",todo_manage:"todos",schedule_manage:"schedule",text_polish:"text",meeting_process:"meetings"};
  return (state.capabilities?.tools || []).map(tool => {
    const label = toolLabels[tool.name] || [tool.name,tool.description];
    return `<a class="module-row" href="#${routes[tool.name] || "console"}"><span class="module-icon">${esc(tool.name.slice(0,2).toUpperCase())}</span><span><b>${esc(label[0])}</b><small>${esc(label[1])}</small></span><span class="risk ${tool.risk_level.toLowerCase()}">${tool.risk_level} · ${tool.data_level}</span></a>`;
  }).join("");
}
function renderOverview() {
  const counts = state.history.reduce((acc,t) => (acc[t.state]=(acc[t.state]||0)+1,acc),{});
  const endpoints = Object.values(state.openapi?.paths || {}).reduce((n,item) => n + Object.keys(item).filter(k => ["get","post","put","patch","delete"].includes(k)).length,0);
  pageRoot.innerHTML = header("OPERATIONS","Agent 操作台","所有主要能力、风险闸门、运行态与接口契约都在这里显式可见。",`<button class="button" id="refreshOverview">刷新状态</button><a class="button primary" href="#api-lab">运行接口体检</a>`)+
  `<section class="metrics"><div class="metric"><small>已注册能力</small><strong>${state.capabilities?.tools?.length ?? "—"}</strong><em>预期 8 个工具</em></div><div class="metric"><small>HTTP 操作</small><strong>${endpoints || "—"}</strong><em>来自 OpenAPI</em></div><div class="metric"><small>当前会话任务</small><strong>${state.history.length}</strong><em>隔离任务账本</em></div><div class="metric"><small>待人工确认</small><strong>${counts.awaiting_confirmation || 0}</strong><em>R2 / R3 闸门</em></div></section>`+
  `<div class="grid-2"><section class="panel span-2"><header class="panel-head"><div><h3>七阶段执行链</h3><p>每个任务都会穿过同一条可审计管线</p></div></header>${rail()}</section><section class="panel"><header class="panel-head"><div><h3>功能入口</h3><p>8 个主要能力均有对应测试入口</p></div></header><div class="module-list">${capabilityRows() || `<div class="empty-state compact">能力清单未加载</div>`}</div></section>`+
  `<div class="stack">${panel("运行配置","公开安全配置，不包含密钥",`<div class="kv"><span>模型提供方</span><b>${esc(state.capabilities?.platform?.model_provider || "—")}</b></div><div class="kv"><span>模型名称</span><span>${esc(state.capabilities?.platform?.model_name || "—")}</span></div><div class="kv"><span>资源模式</span><span>${esc(state.capabilities?.platform?.resource_mode || "—")}</span></div><div class="kv"><span>网络状态</span><span>${state.capabilities?.platform?.network_available ? "可用" : "不可用"}</span></div><div class="kv"><span>文件打开</span><span>${state.capabilities?.platform?.file_open_enabled ? "启用" : "禁用（安全默认）"}</span></div><div class="kv"><span>保留周期</span><span>${esc(state.capabilities?.platform?.retention_days || "—")} 天</span></div>`)}${panel("安全基线","当前运行时声明",subfeatures([["会话隔离","任务查询按会话过滤"],["全链路审计","每次状态变化可回放"],["高风险确认","R2/R3 操作需人工批准"],["密钥不外露","能力接口仅提供非敏感设置"],["本地优先","知识、文件和个人数据本地处理"],["参数白名单","工具参数经 JSON Schema 校验"]]))}</div></div>`;
  $("#refreshOverview").onclick = async () => { await loadRuntime(); renderOverview(); toast("运行状态已刷新"); };
}

function featureShell(config) {
  pageRoot.innerHTML = header(config.eyebrow,config.title,config.description,`<button class="button" data-open-contract="${config.tool}">查看工具契约</button>`)+
  `<div class="grid-2"><section class="panel"><header class="panel-head"><div><h3>${config.formTitle}</h3><p>${config.formSubtitle}</p></div><span class="risk ${config.risk.toLowerCase()}">${config.risk} · ${config.data}</span></header><div class="panel-body"><div id="actionTabs" class="segmented">${config.actions.map((a,i)=>`<button type="button" class="${i===0?"active":""}" data-action="${a[0]}">${a[1]}</button>`).join("")}</div><form id="featureForm"><div id="featureFields"></div><div class="form-actions"><small>提交后可在右侧检查请求、响应与审计</small><button class="button primary" type="submit">执行功能测试</button></div></form></div></section>`+
  `<div class="stack">${panel("可测试子功能",`${config.subs.length} 项已显式列出`,subfeatures(config.subs))}<section class="panel"><header class="panel-head"><div><h3>执行状态</h3><p>统一七阶段状态机</p></div></header><div id="miniRail">${rail()}</div></section></div><div id="liveTaskArea" class="span-2"></div></div>`;
  let action = config.actions[0][0];
  const draw = () => { $("#featureFields").innerHTML = config.fields(action); bindPresets(); config.afterFields?.(action); };
  draw(); bindTabs($("#actionTabs"), next => { action = next; draw(); });
  $("#featureForm").onsubmit = async event => { event.preventDefault(); const prompt = config.prompt(action); if (!prompt) return; await submitTask(prompt); };
  $$("[data-open-contract]").forEach(button => button.onclick = () => showToolContract(button.dataset.openContract));
  if (state.currentTask) renderLiveTask(state.currentTask);
}

function renderConsole() {
  pageRoot.innerHTML = header("UNIVERSAL TASK","通用任务","直接输入自然语言，观察 Agent 如何识别意图、校验参数、评估风险并路由工具。",`<a class="button" href="#tasks">查看历史</a>`)+
  `<div class="grid-2"><section class="panel"><header class="panel-head"><div><h3>自然语言任务</h3><p>适合探索跨模块表达和路由边界</p></div></header><div class="panel-body"><form id="consoleForm">${field("consoleText","任务内容","textarea","例如：1+1等于多少？")}<div class="voice-entry"><button id="voiceButton" class="voice-button" type="button" aria-label="按住说话" title="按住说话">●</button><div class="voice-feedback"><span id="voiceState">正在读取语音状态</span><div class="level-track"><i id="voiceLevel"></i></div></div><button id="voiceCancel" class="button small" type="button" hidden>取消录音</button></div>${presets(["1+1等于多少？","请用一句话说明局域网是什么？","把你好翻译成英文","查询产品保修政策并给出来源","查找项目周报","提醒我30分钟后检查服务","总结这段：本季度完成了三个项目"],"consoleText")}<div class="form-actions"><small>语音只回填输入框，确认内容后再提交</small><button class="button primary">提交任务</button></div></form></div></section>${panel("路由说明","输入会经过意图识别与 Schema 校验",subfeatures([["意图识别","映射到 8 个已注册工具"],["参数补全","缺少关键字段时暂停确认"],["数据分级","按 D0–D3 识别敏感度"],["风险判定","按 R0–R3 决定是否确认"],["端云路由","根据数据与资源选择执行位置"],["审计记录","全过程留下可验证事件"]]))}<div id="liveTaskArea" class="span-2"></div></div>`;
  bindPresets(); bindVoiceEntry(); $("#consoleForm").onsubmit = async e => { e.preventDefault(); await submitTask($("#consoleText").value.trim()); };
  if (state.currentTask) renderLiveTask(state.currentTask);
}

function renderUserTaskList() {
  const root = $("#userTaskList"); if (!root) return;
  const recent = state.history.slice(0, 8);
  root.innerHTML = recent.length ? recent.map(task => `<button type="button" class="user-task-row" data-user-task="${task.id}"><span class="state-pill ${task.state}">${esc(stateMeta[task.state]?.[0] || task.state)}</span><b>${esc(task.request_text)}</b><small>${fmt(task.updated_at)}</small></button>`).join("") : `<div class="empty-state compact">暂无任务</div>`;
  $$('[data-user-task]', root).forEach(button => button.onclick = () => {
    const task = state.history.find(item => item.id === button.dataset.userTask);
    if (task) { state.currentTask = task; renderLiveTask(task); }
  });
}

function renderUserPage() {
  pageRoot.innerHTML = `<section class="user-task-layout">
    <header class="user-heading"><span class="eyebrow">TASK</span><h1>今天需要处理什么？</h1></header>
    <section class="panel user-compose"><div class="panel-body"><form id="consoleForm">
      ${field("consoleText","任务内容","textarea","输入要完成的任务")}
      <div class="voice-entry"><button id="voiceButton" class="voice-button" type="button" aria-label="按住说话" title="按住说话">●</button><div class="voice-feedback"><span id="voiceState">正在读取语音状态</span><div class="level-track"><i id="voiceLevel"></i></div></div><button id="voiceCancel" class="button small" type="button" hidden>取消录音</button></div>
      <div class="form-actions"><span></span><button class="button primary" type="submit">提交任务</button></div>
    </form></div></section>
    <div id="liveTaskArea"></div>
    <section class="user-recent"><header><h2>近期任务</h2><button id="refreshUserTasks" class="button small quiet" type="button">刷新</button></header><div id="userTaskList"></div></section>
  </section>`;
  bindVoiceEntry();
  $("#consoleForm").onsubmit = async event => { event.preventDefault(); await submitTask($("#consoleText").value.trim()); };
  renderUserTaskList();
  $("#refreshUserTasks").onclick = async () => { state.history = await API.get("/tasks?limit=100"); renderUserPage(); };
  if (state.currentTask) renderLiveTask(state.currentTask);
}

const voiceErrors={no_microphone:"未检测到麦克风",voice_device_unavailable:"麦克风设备不可用",recording_too_short:"录音时间过短",silent_recording:"未检测到有效语音",voice_model_missing:"Faster-Whisper 模型缺失",voice_service_busy:"语音服务正忙",voice_transcription_timeout:"语音转写超时"};
function updateVoiceUi(message,level=-90,recording=false) {
  const text=$("#voiceState"),bar=$("#voiceLevel"),button=$("#voiceButton"),cancel=$("#voiceCancel"); if(!text)return;
  text.textContent=message; const percent=Math.max(0,Math.min(100,(level+70)/60*100)); bar.style.width=`${percent}%`;
  button.classList.toggle("recording",recording); button.setAttribute("aria-label",recording?"松开并转写":"按住说话"); cancel.hidden=!recording;
}
async function refreshVoiceStatus() {
  try { state.voiceStatus=await API.get("/voice/status"); updateVoiceUi(state.voiceStatus.message,state.voiceStatus.level_dbfs,state.voiceStatus.state==="recording"); $("#voiceButton").disabled=!state.voiceStatus.available&&!state.voiceRecording; }
  catch(error) { updateVoiceUi("语音服务不可用"); if($("#voiceButton"))$("#voiceButton").disabled=true; }
}
async function beginVoiceRecording() {
  if(state.voiceRecording||state.voiceStartPromise)return; stopSpeech(); state.voiceStopRequested=false;state.voiceCancelRequested=false;
  state.voiceStartPromise=API.post("/voice/recordings",{});
  try { state.voiceRecording=await state.voiceStartPromise; updateVoiceUi("正在录音，松开后转写",state.voiceRecording.level_dbfs,true); state.voicePoll=setInterval(refreshVoiceStatus,150);state.voiceAutoStop=setTimeout(finishVoiceRecording,(state.voiceStatus?.max_recording_seconds||30)*1000);if(state.voiceCancelRequested)await cancelVoiceRecording();else if(state.voiceStopRequested)await finishVoiceRecording(); }
  catch(error) { const code=error.body?.code; updateVoiceUi(voiceErrors[code]||error.message); toast(voiceErrors[code]||error.message,true); }
  finally { state.voiceStartPromise=null; }
}
async function finishVoiceRecording() {
  if(state.voiceStartPromise&&!state.voiceRecording){state.voiceStopRequested=true;return;} const recording=state.voiceRecording; if(!recording)return; state.voiceStopRequested=false; clearInterval(state.voicePoll);clearTimeout(state.voiceAutoStop);state.voicePoll=null;state.voiceAutoStop=null; updateVoiceUi("正在转写，请稍候",-90,false);
  try { const result=await API.post(`/voice/recordings/${recording.id}/stop`,{}); const previous=$("#consoleText").value.trim(),transcript=result.transcript||""; $("#consoleText").value=previous?previous+transcript:transcript; $("#consoleText").focus(); updateVoiceUi(result.limit_reached?"已达到最长录音时限，已回填识别内容":"转写完成，可修改后提交"); }
  catch(error) { const code=error.body?.code; updateVoiceUi(voiceErrors[code]||error.message); toast(voiceErrors[code]||error.message,true); }
  finally { state.voiceRecording=null; }
}
async function cancelVoiceRecording() {
  if(state.voiceStartPromise&&!state.voiceRecording){state.voiceCancelRequested=true;return;} const recording=state.voiceRecording; if(!recording)return; clearInterval(state.voicePoll);clearTimeout(state.voiceAutoStop); state.voicePoll=null;state.voiceAutoStop=null;
  try { await API.post(`/voice/recordings/${recording.id}/cancel`,{}); updateVoiceUi("录音已取消"); } catch(error) { updateVoiceUi(error.message); }
  finally { state.voiceRecording=null; }
}
function bindVoiceEntry() {
  const button=$("#voiceButton"); let pointerActive=false;
  button.onpointerdown=event=>{event.preventDefault();pointerActive=true;button.setPointerCapture?.(event.pointerId);beginVoiceRecording();};
  button.onpointerup=event=>{event.preventDefault();if(pointerActive){pointerActive=false;finishVoiceRecording();}};
  button.onpointercancel=()=>{pointerActive=false;cancelVoiceRecording();};
  button.onclick=event=>{if(event.detail===0)(state.voiceRecording?finishVoiceRecording():beginVoiceRecording());};
  $("#voiceCancel").onclick=cancelVoiceRecording; refreshVoiceStatus();
}

function renderKnowledge() { featureShell({eyebrow:"KNOWLEDGE · R0 / D2",title:"知识库问答",description:"对授权目录中的 TXT、Markdown、DOCX 文档建立本地索引，并返回带来源的答案。",tool:"knowledge_query",risk:"R0",data:"D2",formTitle:"发起知识检索",formSubtitle:"只读操作，无需人工确认",actions:[["query","问答"]],fields:()=>field("knowledgeQuery","问题","textarea","例如：产品保修期是多久？","full")+presets(["产品保修期是多久？","差旅报销标准是什么？","新员工入职需要做什么？","会议室使用有哪些规则？","设备使用有哪些注意事项？"],"knowledgeQuery"),prompt:()=>`查询知识库：${$("#knowledgeQuery").value.trim()}`,subs:[["多格式索引","TXT / MD / DOCX"],["增量同步","按修改时间更新索引"],["语义召回","本地向量与关键词匹配"],["来源引用","文件名与段落定位"],["范围控制","仅检索授权目录"],["敏感脱敏","索引前执行数据分类"]]}); }
function renderFiles() { featureShell({eyebrow:"FILES · R1 / D1",title:"文件查找",description:"搜索授权目录，展示候选文件；真正打开前要求你明确选择。当前安全配置默认禁用系统打开。",tool:"file_open",risk:"R1",data:"D1",formTitle:"查找文件",formSubtitle:"候选选择会作为显式确认步骤",actions:[["search","搜索并选择"]],fields:()=>field("fileQuery","文件关键词","text","例如：项目周报","full")+presets(["项目周报","周报模板","20260721"],"fileQuery"),prompt:()=>`查找并打开文件：${$("#fileQuery").value.trim()}`,subs:[["目录索引","扫描授权根目录"],["模糊搜索","按文件名、扩展名与目录匹配"],["候选排序","相关度与修改时间排序"],["路径摘要","只展示授权根内相对路径"],["人工选择","多候选时暂停确认"],["安全打开","受 AGENT_FILE_OPEN_ENABLED 控制"]]}); }
function renderReminders() { featureShell({eyebrow:"REMINDERS · R1 / D1",title:"提醒管理",description:"创建、查询、取消、完成或清空本地提醒；批量删除会触发 R3 高风险确认。",tool:"reminder_create",risk:"R1",data:"D1",formTitle:"提醒操作",formSubtitle:"支持中文相对时间和周期表达",actions:[["create","创建"],["query","查询"],["cancel","取消"],["complete","完成"],["delete_all","清空全部"]],fields:a=>a==="create"?field("reminderText","提醒内容","text","检查服务")+field("reminderWhen","提醒时间","text","30分钟后 / 明天下午3点")+presets(["30分钟后","明天下午3点","每周一上午9点"],"reminderWhen"):a==="query"?selectField("reminderScope","查询范围",[["next_7_days","未来 7 天"],["overdue","已过期"]],"full"):a==="delete_all"?`<div class="callout bad">此操作会删除全部提醒。Agent 将暂停在 R3 风险确认，不会直接执行。</div>`:field("reminderId","提醒 ID","number","例如：12","full"),prompt:a=>a==="create"?`${$("#reminderWhen").value.trim()}提醒我${$("#reminderText").value.trim()}`:a==="query"?($("#reminderScope").value==="overdue"?"查询已过期提醒":"查看未来7天提醒"):a==="cancel"?`取消提醒 ${$("#reminderId").value}`:a==="complete"?`完成提醒 ${$("#reminderId").value}`:"删除全部提醒",subs:[["相对时间","分钟、小时、明天、后天"],["周期提醒","每周固定日期时间"],["未来查询","未来 7 天活动提醒"],["过期查询","筛出过期未完成项目"],["状态更新","取消或标记完成"],["批量清空","R3 确认后删除全部"]]}); }
function renderTodos() { featureShell({eyebrow:"TODOS · R1 / D1",title:"待办事项",description:"以稳定 ID 管理个人任务，支持筛选、标签、优先级、截止时间和受控删除。",tool:"todo_manage",risk:"R1",data:"D1",formTitle:"待办操作",formSubtitle:"删除动作会进入风险确认",actions:[["create","创建"],["query","查询"],["update","更新"],["complete","完成"],["delete","删除"]],fields:a=>a==="create"?field("todoTitle","标题","text","提交接口测试报告")+selectField("todoPriority","优先级",[["medium","中"],["high","高"],["low","低"]])+field("todoDue","截止表达","text","明天下午3点（可选）")+field("todoTags","标签","text","测试,发布（可选）"):a==="query"?selectField("todoStatus","状态",[["all","全部"],["pending","待处理"],["in_progress","进行中"],["completed","已完成"]])+field("todoKeyword","标题关键词","text","可选"):a==="update"?field("todoId","待办 ID","number","例如：12")+selectField("todoPriority","新优先级",[["high","高"],["medium","中"],["low","低"]]):field("todoId","待办 ID","number","例如：12","full"),prompt:a=>{if(a==="create")return `添加待办 ${$("#todoTitle").value.trim()}，${$("#todoPriority").value==="high"?"高":$("#todoPriority").value==="low"?"低":"中"}优先级${$("#todoDue").value.trim()?`，截止${$("#todoDue").value.trim()}`:""}${$("#todoTags").value.trim()?`，标签${$("#todoTags").value.trim()}`:""}`;if(a==="query")return `${$("#todoStatus").value==="all"?"查看":`查看${$("#todoStatus").selectedOptions[0].text}`}待办${$("#todoKeyword").value.trim()?`，标题包含${$("#todoKeyword").value.trim()}`:""}`;if(a==="update")return `更新待办 ${$("#todoId").value} 为${$("#todoPriority").selectedOptions[0].text}优先级`;return `${a==="complete"?"完成":"删除"}待办 ${$("#todoId").value}`;},subs:[["优先级","高 / 中 / 低"],["标签","最多 20 个分类标签"],["截止时间","中文时间表达解析"],["组合查询","状态、标签、标题、日期范围"],["定点更新","按稳定 ID 修改字段"],["受控删除","删除前执行风险确认"]]}); }
function renderSchedule() { featureShell({eyebrow:"SCHEDULE · R1 / D1",title:"日程管理",description:"创建一次性或重复日程，按时间范围检索，并以稳定 ID 取消。",tool:"schedule_manage",risk:"R1",data:"D1",formTitle:"日程操作",formSubtitle:"重复日程支持每日、每周、每月",actions:[["create","创建"],["query","查询"],["cancel","取消"]],fields:a=>a==="create"?field("scheduleTitle","标题","text","项目例会")+field("scheduleStart","开始时间","text","明天下午2点")+field("scheduleEnd","结束时间","text","明天下午3点（可选）")+field("scheduleLocation","地点","text","A-301（可选）")+selectField("scheduleRepeat","重复",[["none","不重复"],["daily","每天"],["weekly","每周"],["monthly","每月"]])+field("scheduleNotice","提前提醒分钟","number","15"):a==="query"?selectField("scheduleRange","时间范围",[["today","今天"],["tomorrow","明天"],["this_week","本周"],["next_week","下周"]])+field("scheduleKeyword","标题关键词","text","可选"):field("scheduleId","日程 ID","number","例如：12","full"),prompt:a=>a==="create"?`创建日程 ${$("#scheduleStart").value.trim()}${$("#scheduleTitle").value.trim()}${$("#scheduleEnd").value.trim()?`，结束${$("#scheduleEnd").value.trim()}`:""}${$("#scheduleLocation").value.trim()?`，地点${$("#scheduleLocation").value.trim()}`:""}${$("#scheduleRepeat").value!=="none"?`，${$("#scheduleRepeat").selectedOptions[0].text}重复`:""}${$("#scheduleNotice").value?`，提前${$("#scheduleNotice").value}分钟提醒`:""}`:a==="query"?`${$("#scheduleRange").selectedOptions[0].text}有什么安排${$("#scheduleKeyword").value.trim()?`，标题包含${$("#scheduleKeyword").value.trim()}`:""}`:`取消日程 ${$("#scheduleId").value}`,subs:[["一次性日程","标题、起止时间、地点"],["周期规则","每日 / 每周 / 每月"],["星期组合","每周多工作日安排"],["提前通知","0–1440 分钟"],["范围查询","今天、明天、本周、下周、自定义"],["取消日程","按稳定 ID 风险确认"]]}); }
function renderText() { featureShell({eyebrow:"TEXT · R1 / D1",title:"文本处理",description:"在不发送内容的前提下完成润色、总结、语气调整和草拟，并保护日期、金额、电话等事实。",tool:"text_polish",risk:"R1",data:"D1",formTitle:"处理文本",formSubtitle:"MVP 只生成文本，不连接外部发送器",actions:[["polish","润色"],["summarize","总结"],["tone_adjust","语气调整"],["draft","草拟"]],fields:a=>(a==="tone_adjust"?selectField("textTone","目标语气",[["formal","正式"],["casual","轻松"]],"full"):"")+field("textInput","原始内容","textarea","输入需要处理的文本","full")+presets(["项目将在2026年8月1日上线，预算为300万元。","本季度完成了三个项目，分别覆盖知识库、工作流和接口验证。","请尽快提交材料。"],"textInput"),prompt:a=>`${a==="polish"?"润色":a==="summarize"?"总结这段":a==="tone_adjust"?`调整为${$("#textTone").value==="formal"?"正式":"轻松"}语气`:"草拟"}：${$("#textInput").value.trim()}`,subs:[["专业润色","错字与语句流畅度"],["内容总结","长文本压缩"],["语气调整","正式 / 轻松"],["内容草拟","从要点生成短文"],["事实保护","日期、金额、电话原样保留"],["发送隔离","确认文本但不向外发送"]]}); }
function renderMeetings() { const root=state.capabilities?.authorized_roots?.files?.[1]||state.capabilities?.authorized_roots?.files?.[0]||""; const sample=root?`${root}\\项目周报_20260721.txt`:""; featureShell({eyebrow:"MEETING · R2 / D2",title:"会议纪要",description:"读取授权 TXT / Markdown 文稿，生成可追溯 Markdown 纪要；处理前必须人工确认。",tool:"meeting_process",risk:"R2",data:"D2",formTitle:"生成会议纪要",formSubtitle:"源文件必须位于授权目录",actions:[["process","处理文稿"]],fields:()=>field("meetingPath","文稿完整路径","text","例如：F:\\data\\meeting.txt","full")+(sample?presets([sample],"meetingPath"):"")+`<div class="callout warn">R2 操作：确认页会展示影响范围，批准后才读取文稿并写入会议纪要目录。</div>`,prompt:()=>`整理会议纪要 ${$("#meetingPath").value.trim()}`,subs:[["格式校验","仅 TXT / MD"],["授权路径","拒绝目录外文件"],["内容脱敏","处理前识别敏感数据"],["结构提取","决策、行动项、责任人"],["可追溯输出","保留源文件元数据"],["Markdown 交付","写入独立纪要目录"]]}); }

function voicePresetRow(voice={id:"",name:"",reference_wav:"",reference_text:""}) {
  const disabled=isLocked("zipvoice_voices")?"disabled":"";
  return `<div class="voice-preset"><div class="voice-preset-head"><b>音色预设</b><button class="icon-button remove-voice" type="button" title="删除音色" aria-label="删除音色" ${disabled}>×</button></div><div class="form-grid"><div class="field"><label>音色 ID</label><input class="input voice-id" value="${esc(voice.id)}" ${disabled}></div><div class="field"><label>名称</label><input class="input voice-name" value="${esc(voice.name)}" ${disabled}></div><div class="field full"><label>参考 WAV</label><input class="input voice-wav" value="${esc(voice.reference_wav)}" ${disabled}></div><div class="field full"><label>逐字文本</label><textarea class="textarea compact-textarea voice-text" ${disabled}>${esc(voice.reference_text)}</textarea></div></div></div>`;
}
function bindVoicePresets() {
  const rows=$("#voicePresetRows");
  const updateDefault=()=>{const current=$("#set-zipvoice_default_voice_id")?.value||"";const ids=$$(".voice-id",rows).map(input=>input.value.trim()).filter(Boolean);const select=$("#set-zipvoice_default_voice_id");if(!select)return;select.innerHTML=ids.map(id=>`<option value="${esc(id)}" ${id===current?"selected":""}>${esc(id)}</option>`).join("");};
  $$(".remove-voice",rows).forEach(button=>button.onclick=()=>{button.closest(".voice-preset").remove();if(!rows.children.length)rows.insertAdjacentHTML("beforeend",voicePresetRow());bindVoicePresets();updateDefault();});
  $$(".voice-id",rows).forEach(input=>input.oninput=updateDefault);
  $("#addVoice").onclick=()=>{rows.insertAdjacentHTML("beforeend",voicePresetRow());bindVoicePresets();}; updateDefault();
}
function settingValue(name) { const node=$(`#set-${name}`); return node?.type==="checkbox"?node.checked:node?.value??""; }
function collectDesktopSettings() {
  const paths=name=>String(settingValue(name)).split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
  const voices=$$(".voice-preset").map(row=>({id:$(".voice-id",row).value.trim(),name:$(".voice-name",row).value.trim(),reference_wav:$(".voice-wav",row).value.trim(),reference_text:$(".voice-text",row).value.trim()}));
  return {model_provider:settingValue("model_provider"),model_name:settingValue("model_name"),ollama_base_url:settingValue("ollama_base_url"),file_open_enabled:settingValue("file_open_enabled"),authorized_file_roots:paths("authorized_file_roots"),knowledge_roots:paths("knowledge_roots"),tts_provider:settingValue("tts_provider"),zipvoice_model_dir:settingValue("zipvoice_model_dir"),zipvoice_vocoder_path:settingValue("zipvoice_vocoder_path"),zipvoice_num_threads:Number(settingValue("zipvoice_num_threads")),zipvoice_speed:Number(settingValue("zipvoice_speed")),zipvoice_default_voice_id:settingValue("zipvoice_default_voice_id"),zipvoice_voices:voices,voice_enabled:settingValue("voice_enabled"),voice_input_device:settingValue("voice_input_device"),voice_model_dir:settingValue("voice_model_dir"),voice_cpu_threads:Number(settingValue("voice_cpu_threads")),voice_num_workers:Number(settingValue("voice_num_workers")),voice_beam_size:Number(settingValue("voice_beam_size")),voice_vad_enabled:settingValue("voice_vad_enabled"),voice_max_recording_seconds:Number(settingValue("voice_max_recording_seconds"))};
}
async function waitForDesktopRestart() {
  const status=$("#settingsStatus"); const deadline=Date.now()+60000;
  while(Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,700));try{const restart=await API.get("/admin/restart-status");status.textContent=restart.message||restart.state;if(restart.state==="ready"){await loadRuntime();toast(restart.rollback_performed?"新配置失败，已恢复上一份配置":"配置已生效，服务已恢复");await renderSettings();return;}if(restart.state==="failed"){toast(restart.message,true);return;}}catch(error){status.textContent="服务正在重启，等待恢复";}}
  toast("服务重启等待超时，请检查终端日志",true);
}
async function renderSettings() {
  try { const [settings,devices]=await Promise.all([API.get("/admin/settings"),API.get("/voice/devices").catch(()=>[])]);state.desktopSettings=settings;state.voiceDevices=devices; }
  catch(error){pageRoot.innerHTML=header("DESKTOP SETTINGS","设置","管理本机模型、目录、语音和桌面能力。")+`<div class="callout bad">${esc(error.message)}</div>`;return;}
  const s=state.desktopSettings; const modelOptions=[...new Set([s.model_name,...s.ollama_models])].filter(Boolean).map(name=>[name,name]); const deviceOptions=[["","系统默认"],...state.voiceDevices.map(device=>[device.id,`${device.name}${device.default?"（默认）":""}`])];
  pageRoot.innerHTML=header("DESKTOP SETTINGS","设置","保存后由桌面监督模式自动重启；外部环境变量锁定的字段保持只读。",`<span id="settingsStatus" class="runtime-badge ${s.supervised?"ok":""}"><i></i>${s.supervised?"自动重启已启用":"serve 模式需手动重启"}</span>`)+`<form id="settingsForm" class="settings-stack"><div class="grid-2">${panel("模型","Mock、Ollama 与离线包运行态",`<div class="form-grid">${settingsSelect("model_provider","模型提供方",s.model_provider,[["mock","Mock（离线确定性）"],["ollama","Ollama（真实模型）"],["llamacpp","llama.cpp（离线包整栈脚本管理）",s.model_provider!=="llamacpp"]])}${settingsSelect("model_name","模型",s.model_name,modelOptions)}${settingsInput("ollama_base_url","Ollama 地址",s.ollama_base_url,"text","full")}</div>`)}${panel("Windows 与知识库",`${s.knowledge_index.document_count} 份文档 · ${s.knowledge_index.index_exists?"索引存在":"尚未索引"}`,`${settingsToggle("file_open_enabled","允许用 Windows 默认应用打开授权文件",s.file_open_enabled)}<div class="form-grid settings-space">${settingsTextarea("authorized_file_roots","授权文件目录（每行一个）",s.authorized_file_roots.join("\n"),"full")}${settingsTextarea("knowledge_roots","知识库目录（每行一个）",s.knowledge_roots.join("\n"),"full")}</div><div class="settings-actions"><button id="reindexKnowledge" class="button" type="button">重建知识索引</button><button id="testNotification" class="button" type="button">发送测试通知</button></div>`)}<section class="panel span-2"><header class="panel-head"><div><h3>ZipVoice 输出</h3><p>模型路径、推理参数和参考音色</p></div></header><div class="panel-body">${settingsSelect("tts_provider","TTS 状态",s.tts_provider,[["disabled","关闭"],["zipvoice","启用 ZipVoice"]])}<div class="form-grid settings-space">${settingsInput("zipvoice_model_dir","模型目录",s.zipvoice_model_dir,"text","full")}${settingsInput("zipvoice_vocoder_path","Vocoder 文件",s.zipvoice_vocoder_path,"text","full")}${settingsInput("zipvoice_num_threads","线程",s.zipvoice_num_threads,"number")}${settingsInput("zipvoice_speed","语速",s.zipvoice_speed,"number")}${settingsSelect("zipvoice_default_voice_id","默认音色",s.zipvoice_default_voice_id,s.zipvoice_voices.map(v=>[v.id,v.id]))}</div><div class="voice-preset-list" id="voicePresetRows">${s.zipvoice_voices.map(voicePresetRow).join("")||voicePresetRow()}</div><button id="addVoice" class="button small" type="button" ${isLocked("zipvoice_voices")?"disabled":""}>添加音色</button></div></section><section class="panel span-2"><header class="panel-head"><div><h3>麦克风与 Faster-Whisper</h3><p>CPU INT8 · 单工作线程 · PCM 仅驻留内存</p></div></header><div class="panel-body">${settingsToggle("voice_enabled","启用按键说话",s.voice_enabled)}<div class="form-grid settings-space">${settingsSelect("voice_input_device","输入设备",s.voice_input_device,deviceOptions)}${settingsInput("voice_model_dir","模型目录",s.voice_model_dir,"text")}${settingsInput("voice_cpu_threads","CPU 线程",s.voice_cpu_threads,"number")}${settingsInput("voice_num_workers","工作线程",s.voice_num_workers,"number")}${settingsInput("voice_beam_size","Beam size",s.voice_beam_size,"number")}${settingsInput("voice_max_recording_seconds","最长录音（秒）",s.voice_max_recording_seconds,"number")}</div>${settingsToggle("voice_vad_enabled","启用 VAD 语音活动检测",s.voice_vad_enabled)}</div></section></div><div class="settings-save"><span>API 密钥不会显示，也不会被本页覆盖。</span><button class="button primary" type="submit">保存并应用</button></div></form>`;
  bindVoicePresets();
  $("#reindexKnowledge").onclick=async()=>{try{const report=await API.post("/admin/knowledge/reindex",{});toast(`索引完成：扫描 ${report.scanned}，更新 ${report.imported}`);}catch(error){toast(error.message,true);}};
  $("#testNotification").onclick=async()=>{try{await API.post("/admin/notifications/test",{});toast("测试通知已发送");}catch(error){toast(error.message,true);}};
  $("#settingsForm").onsubmit=async event=>{event.preventDefault();const button=$("#settingsForm button[type=submit]");button.disabled=true;try{const updated=await API.put("/admin/settings",collectDesktopSettings());state.desktopSettings=updated;toast("配置已保存");if(updated.supervised)waitForDesktopRestart();else{$("#settingsStatus").textContent="配置已保存，请手动重启 serve";}}catch(error){toast(error.message,true);button.disabled=false;}};
}

async function submitTask(text) {
  if (!text || /[:：]\s*$/.test(text)) { toast("请先填写完整参数", true); return; }
  try {
    const task = await API.post("/tasks", {text}); state.currentTask = task; state.history.unshift(task);
    renderLiveTask(task); renderUserTaskList(); selectTask(task, appMode === "developer"); connectTask(task.id); toast(`任务 ${shortId(task.id)} 已提交`);
  } catch (error) { toast(error.message, true); }
}
function connectTask(id) {
  state.eventSources.get(id)?.close(); const source = new EventSource(`/tasks/${id}/events`); state.eventSources.set(id,source);
  source.addEventListener("task", event => { const task=JSON.parse(event.data); updateTask(task); if(terminal.has(task.state)) source.close(); });
  source.onerror = () => { if (!terminal.has(state.currentTask?.state)) toast("状态流暂时中断，浏览器会自动重连",true); };
}
function updateTask(task) {
  state.currentTask=task; const index=state.history.findIndex(t=>t.id===task.id); if(index>=0) state.history[index]=task; else state.history.unshift(task);
  renderLiveTask(task); renderUserTaskList(); selectTask(task,false);
}
function resultData(task) { return task?.result?.receipt || task?.result || {}; }
function resultTool(task,result) { return task?.context?.intent || result?.tool_name || ""; }
function resultItemId(item) { return item?.id ?? item?.schedule_id ?? ""; }
function resultItemTitle(item) { return item?.title || item?.text || item?.name || `记录 ${resultItemId(item)}`; }
function resultField(label,value) {
  if (value === undefined || value === null || value === "") return "";
  return `<span class="result-field"><small>${esc(label)}</small><b>${esc(value)}</b></span>`;
}
function resultQuickAction(label,command) {
  return `<button type="button" class="button small quiet" data-quick-command="${esc(command)}">${esc(label)}</button>`;
}
function renderResultItem(tool,item,{actions=true}={}) {
  const id = resultItemId(item);
  const fields = [
    resultField("编号",id),
    resultField("状态",item?.status),
    resultField("时间",item?.due_at ? fmt(item.due_at) : ""),
    resultField("开始",item?.start_at ? fmt(item.start_at) : ""),
    resultField("结束",item?.end_at ? fmt(item.end_at) : ""),
    resultField("优先级",item?.priority),
    resultField("地点",item?.location),
    resultField("标签",Array.isArray(item?.tags) ? item.tags.join("、") : ""),
  ].join("");
  let actionMarkup = "";
  if (actions && id && tool === "reminder_create" && ["active","notified"].includes(item.status)) {
    actionMarkup = resultQuickAction("完成此提醒",`完成提醒 ${id}`) + resultQuickAction("取消此提醒",`取消提醒 ${id}`);
  } else if (actions && id && tool === "todo_manage") {
    actionMarkup = (item.status !== "completed" ? resultQuickAction("完成此待办",`完成待办 ${id}`) : "") + resultQuickAction("删除此待办",`删除待办 ${id}`);
  } else if (actions && id && tool === "schedule_manage") {
    actionMarkup = resultQuickAction("取消此日程",`取消日程 ${id}`);
  }
  return `<article class="result-item"><div class="result-item-head"><strong>${esc(resultItemTitle(item))}</strong>${id ? `<span class="mono">#${esc(id)}</span>` : ""}</div><div class="result-fields">${fields}</div>${actionMarkup ? `<div class="result-item-actions">${actionMarkup}</div>` : ""}</article>`;
}
function renderStructuredOutput(task,result,output) {
  const tool = resultTool(task,result);
  if (Array.isArray(output?.items)) {
    if (!output.items.length) return `<div class="result-items"><div class="empty-state compact">当前查询没有匹配记录</div></div>`;
    return `<div class="result-items">${output.items.map(item=>renderResultItem(tool,item)).join("")}</div>`;
  }
  if (output?.item && typeof output.item === "object") {
    return `<div class="result-items">${renderResultItem(tool,output.item)}</div>`;
  }
  if (output?.deleted && typeof output.deleted === "object") {
    return `<div class="result-items">${renderResultItem(tool,output.deleted,{actions:false})}</div>`;
  }
  if (Array.isArray(output?.deleted_items)) {
    if (!output.deleted_items.length) return `<div class="result-items"><div class="empty-state compact">没有可删除的记录</div></div>`;
    return `<div class="result-items">${output.deleted_items.map(item=>renderResultItem(tool,item,{actions:false})).join("")}</div>`;
  }
  if (output && Object.prototype.hasOwnProperty.call(output,"deleted_count")) {
    return `<div class="result-items"><div class="result-item">已删除 <strong>${esc(output.deleted_count)}</strong> 条记录</div></div>`;
  }
  return "";
}
function bindResultActions(root) {
  $$('[data-quick-command]',root).forEach(button=>button.onclick=async()=>{
    button.disabled=true;
    await submitTask(button.dataset.quickCommand);
  });
}
function speakableText(task) {
  if (task?.state !== "completed") return "";
  const result=resultData(task), output=result.output||{};
  return [output.answer,output.text,output.message,result.message,result.output_summary].find(value=>typeof value==="string"&&value.trim())||"";
}
function speechControls(task) {
  if (!state.capabilities?.tts?.enabled || !speakableText(task)) return "";
  const speech=state.speechByTask.get(task.id)||{};
  const tts=state.capabilities.tts, voices=(tts.voices||[]).filter(voice=>voice.available!==false);
  const selectedVoice=speech.voiceId||tts.default_voice_id||voices[0]?.id||"";
  const playing=state.speechTaskId===task.id&&!state.speechAudio.paused;
  const status=speech.loading?"正在生成语音":speech.error?speech.error:speech.artifact?`${speech.artifact.voice_label} · ${speech.artifact.duration_seconds.toFixed(1)} 秒 · ${speech.artifact.sample_rate} Hz`:"尚未生成";
  const options=voices.map(voice=>`<option value="${esc(voice.id)}" ${voice.id===selectedVoice?"selected":""}>${esc(voice.label)}</option>`).join("");
  return `<div class="speech-controls" aria-label="语音播放控制"><label class="speech-voice"><span>音色</span><select data-speech-voice aria-label="音色" ${speech.loading?"disabled":""}>${options}</select></label><button type="button" class="speech-icon" data-speech-action="play" title="播放" aria-label="播放" ${speech.loading||!voices.length?"disabled":""}>▶</button><button type="button" class="speech-icon" data-speech-action="stop" title="停止" aria-label="停止" ${playing?"":"disabled"}>■</button><button type="button" class="speech-icon" data-speech-action="regenerate" title="重新生成" aria-label="重新生成" ${speech.loading||!voices.length?"disabled":""}>↻</button><span class="speech-status">ZipVoice · ${esc(status)}</span></div>`;
}
function refreshSpeechTask(taskId) {
  if (state.currentTask?.id===taskId) renderLiveTask(state.currentTask);
}
function stopSpeech() {
  const taskId=state.speechTaskId;
  state.speechAudio.pause();
  state.speechAudio.currentTime=0;
  state.speechTaskId=null;
  if(taskId) refreshSpeechTask(taskId);
}
state.speechAudio.addEventListener("ended",()=>{
  const taskId=state.speechTaskId;
  state.speechTaskId=null;
  if(taskId) refreshSpeechTask(taskId);
});
async function playTaskSpeech(task,regenerate=false) {
  let speech=state.speechByTask.get(task.id)||{};
  const voiceId=speech.voiceId||state.capabilities?.tts?.default_voice_id||state.capabilities?.tts?.voices?.[0]?.id;
  try {
    if(regenerate||!speech.artifact||speech.artifact.voice_id!==voiceId) {
      speech={...speech,loading:true,error:""}; state.speechByTask.set(task.id,speech); refreshSpeechTask(task.id);
      const artifact=await API.post(`/tasks/${task.id}/speech`,{voice_id:voiceId});
      speech={artifact,voiceId,loading:false,error:""}; state.speechByTask.set(task.id,speech);
    }
    if(state.speechTaskId&&state.speechTaskId!==task.id) stopSpeech();
    state.speechAudio.pause(); state.speechAudio.currentTime=0;
    state.speechAudio.src=`${speech.artifact.audio_url}?v=${speech.artifact.version_id}`;
    state.speechTaskId=task.id;
    await state.speechAudio.play(); refreshSpeechTask(task.id);
  } catch(error) {
    state.speechAudio.pause(); state.speechTaskId=null;
    state.speechByTask.set(task.id,{...speech,loading:false,error:error.message}); refreshSpeechTask(task.id);
    toast(error.message,true);
  }
}
function bindSpeechControls(task,root) {
  const voiceSelect=$('[data-speech-voice]',root);
  if(voiceSelect) voiceSelect.onchange=()=>{
    const selectedVoiceId=voiceSelect.value;
    stopSpeech();
    const current=state.speechByTask.get(task.id)||{};
    state.speechByTask.set(task.id,{...current,voiceId:selectedVoiceId,artifact:null,error:""});
    refreshSpeechTask(task.id);
  };
  $$('[data-speech-action]',root).forEach(button=>button.onclick=()=>{
    const action=button.dataset.speechAction;
    if(action==="stop") stopSpeech();
    else playTaskSpeech(task,action==="regenerate");
  });
}
function renderLiveTask(task) {
  const area=$("#liveTaskArea"); if(!area)return; const meta=stateMeta[task.state]||[task.state,0,""]; const result=resultData(task); const output=result.output||{};
  let content=""; if(task.state==="completed") content=output.answer||output.text||output.message||result.message||result.output_summary||"处理完成"; else if(task.error) content=task.error;
  const sources=output.sources||[];
  const structured = task.state==="completed" ? renderStructuredOutput(task,result,output) : "";
  const terminal = result.type==="clarification" || result.type==="unsupported";
  const notice = output.notice || result.notice;
  const candidateMarkup = terminal && Array.isArray(result.candidates) && result.candidates.length ? `<div class="sources">${result.candidates.map(s=>{const name=String(s.name||s.file||"候选");const date=String(s.date||"").replace(/\D/g,"");const question=date?`${name.includes("项目周报")?"项目周报":"周报"}_${date} 的进展内容`:`${name.replace(/\.[a-z0-9]+$/i,"")} 的进展内容`;return `<button type="button" class="source-chip" style="cursor:pointer" data-clarity-question="${esc(question)}" title="点击填入问句">${esc(name)} · ${esc(s.date||s.path_summary||"")}</button>`;}).join("")}</div>` : "";
  const resultBody = `${content ? `<strong>${terminal?"说明":task.state==="completed"?"执行结果":"错误"}</strong>${esc(content)}${notice?`<div class="callout">${esc(notice)}</div>`:""}${sources.length?`<div class="sources">${sources.map(s=>`<span class="source-chip">${esc(s.file||s.document||"来源")} · ${esc(s.date || s.section || s.position || "全文")}</span>`).join("")}</div>`:""}${candidateMarkup}` : ""}${structured}${speechControls(task)}`;
  const inspectorAction = appMode === "developer" ? `<button class="button small" data-inspect-task>在检查器中查看</button>` : "";
  area.innerHTML=`<section class="panel task-card"><header class="panel-head"><div><h3><span class="state-pill ${task.state}">${meta[0]}</span> · ${shortId(task.id)}</h3><p class="task-summary">${task.state==="completed"?"任务已完成":task.context?.intent?`正在处理：${esc(task.context.intent)}`:"正在处理任务"}</p></div>${inspectorAction}</header>${rail(task)}${renderConfirmation(task)}${resultBody?`<div class="task-result">${resultBody}</div>`:""}</section>`;
  $("#miniRail") && ($("#miniRail").innerHTML=rail(task)); const inspect=$("[data-inspect-task]",area); if(inspect)inspect.onclick=()=>openInspector(); bindConfirmation(task,area); bindResultActions(area); bindSpeechControls(task,area);
  $$('[data-clarity-question]',area).forEach(btn=>btn.onclick=()=>{const question=btn.dataset.clarityQuestion,input=$("#consoleText"); if(question&&input){input.value=question; input.focus();}});
}
const FIELD_LABELS={when:"具体时间",start_text:"开始时间",end_text:"结束时间",title:"标题",source_path:"文稿路径",selected_path:"文件",query:"关键词",text:"正文",id:"编号"};
function renderConfirmation(task) {
  if(task.state!=="awaiting_confirmation")return""; const data=task.result||{}; const type=data.type; let body="";
  if(type==="missing_fields") body=`<p>${esc(data.message||"请补充缺失参数")}</p>${(data.fields||[]).map(name=>field(`confirm-${name}`,FIELD_LABELS[name]||name,"text",name==="when"?"例如：15:00":"请输入内容","full")).join("")}`;
  else if(type==="candidate_confirmation") { const candidates=data.receipt?.output?.candidates||[]; body=`<p>选择一个候选文件后继续：</p>${candidates.map((f,i)=>`<label class="candidate"><input type="radio" name="candidate" value="${esc(f.path)}" ${i===0?"checked":""}><span><b>${esc(f.name)}</b><small>${esc(f.path_summary||f.path)} · ${fmt(f.modified_at)}</small></span></label>`).join("")}`; }
  else { const info=data.confirmation||{}; body=`<p>${esc(info.content||data.message||"此操作需要人工确认")}</p><div>${esc(info.impact||"")}</div>`; }
  const missing=(data.fields||[]).map(name=>FIELD_LABELS[name]||name).join("、");
  const title=type==="missing_fields"?`请补充信息${missing?` · ${missing}`:""}`:type==="candidate_confirmation"?"请选择一个选项":`人工确认闸门 · ${task.risk_level}`;
  return `<div class="confirmation"><h4>${esc(title)}</h4>${body}<div class="form-actions"><button class="button danger small" data-reject>拒绝</button><button class="button primary small" data-confirm>确认并继续</button></div></div>`;
}
function bindConfirmation(task,root) {
  const confirm=$("[data-confirm]",root), reject=$("[data-reject]",root); if(!confirm)return;
  confirm.onclick=async()=>{const data=task.result||{},args={}; if(data.type==="missing_fields") (data.fields||[]).forEach(name=>args[name]=$(`#confirm-${name}`,root)?.value.trim()||""); if(data.type==="candidate_confirmation") args.selected_path=$("input[name=candidate]:checked",root)?.value||""; confirm.disabled=true; try{updateTask(await API.post(`/tasks/${task.id}/confirm`,{approved:true,arguments:args}));}catch(e){toast(e.message,true);confirm.disabled=false;}};
  reject.onclick=async()=>{reject.disabled=true;try{updateTask(await API.post(`/tasks/${task.id}/confirm`,{approved:false,arguments:{}}));}catch(e){toast(e.message,true);reject.disabled=false;}};
}

function selectTask(task, open=true) { state.currentTask=task; if(appMode!=="developer")return; renderInspector(); if(open && window.innerWidth<=1180) openInspector(); }
function openInspector(){ $("#inspector")?.classList.add("open"); }
function closeInspector(){ $("#inspector")?.classList.remove("open"); }
async function renderInspector() {
  const root=$("#inspectorContent"), task=state.currentTask; if(!task){root.innerHTML=`<div class="empty-state compact"><b>尚未选择任务</b><p>提交功能测试或从任务历史中选择一条记录。</p></div>`;return;}
  if(state.inspectorTab==="response") root.innerHTML=`<div class="inspector-block"><h3>TASK</h3><div class="kv"><span>ID</span><span class="mono">${esc(task.id)}</span></div><div class="kv"><span>状态</span><span>${esc(task.state)}</span></div><div class="kv"><span>风险 / 数据</span><span>${esc(task.risk_level)} / ${esc(task.data_level)}</span></div><div class="kv"><span>更新时间</span><span>${fmt(task.updated_at)}</span></div></div><div class="inspector-block"><h3>REQUEST</h3><pre class="json-view">${esc(pretty({text:task.request_text,session_id:task.session_id}))}</pre></div><div class="inspector-block"><h3>RESPONSE</h3><pre class="json-view">${esc(pretty(task))}</pre></div>`;
  else if(state.inspectorTab==="contract") { const tool=task.context?.intent||resultData(task).tool_name; root.innerHTML=toolContractHtml(tool); }
  else { root.innerHTML=`<div class="empty-state compact"><b>正在加载审计链</b></div>`; try{const events=await API.get(`/tasks/${task.id}/audit`);root.innerHTML=events.map(e=>`<div class="audit-event ${e.success?"":"fail"}"><b>${esc(e.event_type)}</b><small>${fmt(e.timestamp)} · ${e.success?"成功":"失败"}</small><small>${esc(e.decision||e.output_summary||"")}</small></div>`).join("")||`<div class="empty-state compact">暂无审计事件</div>`;}catch(e){root.innerHTML=`<div class="callout bad">${esc(e.message)}</div>`;}
  }
}
function toolContractHtml(name) { const tool=state.capabilities?.tools?.find(t=>t.name===name); if(!tool)return`<div class="empty-state compact"><b>未匹配工具契约</b><p>该任务尚未完成意图识别。</p></div>`; const props=tool.parameters_schema?.properties||{};return`<div class="inspector-block"><h3>TOOL CONTRACT</h3><div class="kv"><span>工具</span><b>${esc(tool.name)}</b></div><div class="kv"><span>风险 / 数据</span><span>${esc(tool.risk_level)} / ${esc(tool.data_level)}</span></div><div class="kv"><span>超时</span><span>${esc(tool.timeout_seconds)} 秒</span></div></div><table class="schema-table"><thead><tr><th>字段</th><th>类型</th><th>约束</th></tr></thead><tbody>${Object.entries(props).map(([key,p])=>`<tr><td class="mono">${esc(key)}</td><td>${esc(p.type||"—")}</td><td>${esc((p.enum||[]).join(" / ")||p.format||"")}</td></tr>`).join("")}</tbody></table><div class="inspector-block" style="margin-top:14px"><h3>JSON SCHEMA</h3><pre class="json-view">${esc(pretty(tool.parameters_schema))}</pre></div>`; }
function showToolContract(name){state.inspectorTab="contract";$$('[data-inspector-tab]').forEach(b=>b.classList.toggle("active",b.dataset.inspectorTab==="contract"));const fake=state.currentTask;if(!fake){$("#inspectorContent").innerHTML=toolContractHtml(name);}else{$("#inspectorContent").innerHTML=toolContractHtml(name);}openInspector();}

async function renderTasks() {
  pageRoot.innerHTML=header("TASK LEDGER","任务历史","浏览当前会话的任务、状态、风险等级与更新时间；点击任意记录查看完整响应和审计。",`<button class="button" id="refreshTasks">刷新</button>`)+`<section class="panel"><header class="panel-head"><div><h3>当前会话</h3><p>最多显示最近 100 条，其他会话数据不可见</p></div><select id="taskFilter" class="select" style="width:150px"><option value="all">全部状态</option><option value="completed">已完成</option><option value="awaiting_confirmation">待确认</option><option value="failed">失败</option><option value="cancelled">已取消</option></select></header><div id="taskTable"></div></section>`;
  const draw=()=>{const filter=$("#taskFilter").value,items=filter==="all"?state.history:state.history.filter(t=>t.state===filter);$("#taskTable").innerHTML=items.length?`<table class="task-table"><thead><tr><th>状态</th><th>任务</th><th>工具</th><th>风险</th><th>更新时间</th></tr></thead><tbody>${items.map(t=>`<tr data-task-id="${t.id}"><td><span class="state-pill ${t.state}">${esc(stateMeta[t.state]?.[0]||t.state)}</span></td><td><b>${esc(t.request_text)}</b><small class="mono">${shortId(t.id)}</small></td><td>${esc(t.context?.intent||resultData(t).tool_name||"—")}</td><td>${esc(t.risk_level)} / ${esc(t.data_level)}</td><td>${fmt(t.updated_at)}</td></tr>`).join("")}</tbody></table>`:`<div class="empty-state"><b>没有匹配任务</b><p>提交一个功能测试后会显示在这里。</p></div>`;$$('[data-task-id]').forEach(row=>row.onclick=()=>{const t=state.history.find(x=>x.id===row.dataset.taskId);if(t)selectTask(t);});};
  draw(); $("#taskFilter").onchange=draw; $("#refreshTasks").onclick=async()=>{state.history=await API.get("/tasks?limit=100");draw();toast("任务历史已刷新");};
}

async function renderLogs() {
  pageRoot.innerHTML = header("RECENT LOGS","最近日志","只显示进程内最近 200 条脱敏记录。",`<button class="button primary" id="refreshLogs">刷新</button>`)+`<section class="panel"><div id="logTable"><div class="empty-state compact">正在读取日志</div></div></section>`;
  const draw = async () => {
    try {
      const payload = await API.get("/developer/logs");
      $("#logTable").innerHTML = payload.items.length ? `<table class="task-table log-table"><thead><tr><th>时间</th><th>级别</th><th>模块</th><th>消息</th></tr></thead><tbody>${payload.items.slice().reverse().map(item=>`<tr><td>${fmt(item.timestamp)}</td><td>${esc(item.level)}</td><td class="mono">${esc(item.module)}</td><td>${esc(item.message)}</td></tr>`).join("")}</tbody></table>` : `<div class="empty-state compact">暂无日志</div>`;
    } catch (error) { $("#logTable").innerHTML=`<div class="callout bad">${esc(error.message)}</div>`; }
  };
  $("#refreshLogs").onclick = draw;
  await draw();
}

async function runApiChecks() {
  const button=$("#runChecks");button.disabled=true;state.apiChecks=[];const cases=[
    ["GET","/health"],["GET","/meta/capabilities"],["GET","/openapi.json"],["GET","/tasks?limit=5"]
  ];
  for(const [method,path] of cases){try{const r=await API.request(path,{method});state.apiChecks.push({method,path,ok:true,status:r.status,elapsed:r.elapsed,body:r.body});}catch(e){state.apiChecks.push({method,path,ok:false,status:e.status||0,elapsed:0,body:e.body||e.message});}drawApiChecks();}
  button.disabled=false;toast(state.apiChecks.every(c=>c.ok)?"接口体检全部通过":"接口体检存在失败项",!state.apiChecks.every(c=>c.ok));
}
function drawApiChecks(){const root=$("#apiChecks");if(!root)return;root.innerHTML=state.apiChecks.length?state.apiChecks.map((c,i)=>`<button class="api-row" data-check="${i}" style="width:100%;border-left:0;border-right:0;border-top:0;background:#fff;text-align:left;cursor:pointer"><span class="method">${c.method}</span><span class="mono">${esc(c.path)}</span><span class="api-status ${c.ok?"pass":"fail"}">${c.ok?`${c.status} · ${c.elapsed}ms`:`失败 ${c.status}`}</span></button>`).join(""):`<div class="empty-state compact"><b>尚未运行体检</b><p>仅执行只读、安全的接口检查。</p></div>`;$$('[data-check]').forEach(b=>b.onclick=()=>{$("#customResponse").textContent=pretty(state.apiChecks[Number(b.dataset.check)]);});}
async function renderApiLab(){const operations=[];for(const [path,item] of Object.entries(state.openapi?.paths||{}))for(const method of Object.keys(item))if(["get","post","put","patch","delete"].includes(method))operations.push([method.toUpperCase(),path,item[method].summary||item[method].description||""]);pageRoot.innerHTML=header("CONTRACT LAB","接口测试中心","从实时 OpenAPI 发现接口，执行安全体检、查看工具契约，并可发送自定义 HTTP 请求。",`<a class="button" href="/docs" target="_blank">Swagger UI ↗</a><button class="button primary" id="runChecks">运行只读体检</button>`)+`<div class="grid-2"><section class="panel"><header class="panel-head"><div><h3>接口清单</h3><p>${operations.length} 个 HTTP 操作 · 来自 /openapi.json</p></div></header><div>${operations.map(([m,p,s])=>`<div class="api-row"><span class="method">${m}</span><span><b class="mono">${esc(p)}</b><small style="display:block;color:var(--muted)">${esc(s)}</small></span><span class="api-status">已发现</span></div>`).join("")}</div></section><section class="panel"><header class="panel-head"><div><h3>接口体检</h3><p>健康、能力、OpenAPI、任务列表</p></div></header><div id="apiChecks"></div></section><section class="panel"><header class="panel-head"><div><h3>自定义请求</h3><p>可测试任意已暴露路径</p></div></header><div class="panel-body"><form id="customRequest"><div class="form-grid">${selectField("customMethod","方法",[["GET","GET"],["POST","POST"]])}${field("customPath","路径","text","/health")} ${field("customBody","JSON 请求体","textarea",'{"text":"查询产品保修政策"}',"full")}</div><div class="form-actions"><small>POST 请求体必须为合法 JSON</small><button class="button primary">发送请求</button></div></form></div></section><section class="panel"><header class="panel-head"><div><h3>原始响应</h3><p>点击体检项或发送自定义请求</p></div></header><div class="panel-body"><pre id="customResponse" class="json-view">{}</pre></div></section><section class="panel span-2"><header class="panel-head"><div><h3>工具契约</h3><p>${state.capabilities?.tools?.length||0} 个工具 · 参数、枚举、风险与数据等级</p></div></header><div class="module-list">${capabilityRows()}</div></section></div>`;drawApiChecks();$("#runChecks").onclick=runApiChecks;$("#customMethod").onchange=()=>{$("#customBody").closest(".field").style.display=$("#customMethod").value==="GET"?"none":"grid";};$("#customRequest").onsubmit=async e=>{e.preventDefault();const method=$("#customMethod").value,path=$("#customPath").value.trim();let body;try{if(method!=="GET")body=JSON.stringify(JSON.parse($("#customBody").value||"{}"));const r=await API.request(path,{method,body});$("#customResponse").textContent=pretty(r);toast(`${method} ${path} 成功`);}catch(err){$("#customResponse").textContent=pretty({error:err.message,status:err.status,body:err.body});toast(err.message,true);}};}

function currentRoute(){const route=location.hash.replace(/^#/,"")||"overview";return routeInfo[route]?route:"overview";}
async function renderRoute(){const route=currentRoute(),info=routeInfo[route];$("#pageEyebrow").textContent=info[0];$("#pageTitle").textContent=info[1];$$('[data-route]').forEach(a=>a.classList.toggle("active",a.dataset.route===route));closeNavigation();const renderers={overview:renderOverview,console:renderConsole,knowledge:renderKnowledge,files:renderFiles,reminders:renderReminders,todos:renderTodos,schedule:renderSchedule,text:renderText,meetings:renderMeetings,"api-lab":renderApiLab,tasks:renderTasks,settings:renderSettings,logs:renderLogs};await renderers[route]();pageRoot.focus({preventScroll:true});window.scrollTo(0,0);}
function closeNavigation(){const sidebar=$("#sidebar"),backdrop=$("#navBackdrop"),menu=$("#menuButton");if(sidebar)sidebar.classList.remove("open");if(backdrop)backdrop.hidden=true;if(menu)menu.setAttribute("aria-expanded","false");}

if($("#menuButton"))$("#menuButton").onclick=()=>{const open=$("#sidebar").classList.toggle("open");$("#navBackdrop").hidden=!open;$("#menuButton").setAttribute("aria-expanded",String(open));};
if($("#navBackdrop"))$("#navBackdrop").onclick=closeNavigation;if($("#inspectorButton"))$("#inspectorButton").onclick=openInspector;if($("#closeInspector"))$("#closeInspector").onclick=closeInspector;
$$('[data-inspector-tab]').forEach(button=>button.onclick=()=>{state.inspectorTab=button.dataset.inspectorTab;$$('[data-inspector-tab]').forEach(b=>b.classList.toggle("active",b===button));renderInspector();});
if(appMode==="developer")window.addEventListener("hashchange",renderRoute);
window.addEventListener("beforeunload",()=>state.eventSources.forEach(source=>source.close()));

function bindUserLogin() {
  const dialog=$("#developerLogin"), password=$("#developerPassword"), error=$("#loginError");
  $("#developerEntry").onclick=()=>{error.textContent="";password.value="";dialog.showModal();password.focus();};
  const close=()=>dialog.close(); $("#closeLogin").onclick=close;$("#cancelLogin").onclick=close;
  $("#developerLoginForm").onsubmit=async event=>{event.preventDefault();error.textContent="";try{await API.post("/auth/developer/login",{password:password.value});location.assign("/developer");}catch(loginError){error.textContent=loginError.message;password.select();}};
}

(async function boot(){
  const auth=await API.get("/auth/me");
  if(appMode==="developer"&&auth.role!=="developer"){location.replace("/");return;}
  await loadRuntime();
  if(appMode==="user"){
    bindUserLogin(); state.currentTask=state.history[0]||null; renderUserPage();
  }else{
    $("#developerLogout").onclick=async()=>{await API.post("/auth/logout",{});location.replace("/");};
    await renderRoute();
  }
})();
