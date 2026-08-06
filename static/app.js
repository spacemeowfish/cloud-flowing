"use strict";

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
  async post(path, body) { return (await this.request(path, {method:"POST", body:JSON.stringify(body)})).body; }
};

const state = {
  capabilities:null, openapi:null, health:null, history:[], currentTask:null,
  eventSources:new Map(), inspectorTab:"response", apiChecks:[]
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
  "api-lab":["CONTRACT LAB","接口测试中心"], tasks:["TASK LEDGER","任务历史"]
};
const toolLabels = {
  file_open:["文件查找","查找、候选选择、确认打开"], knowledge_query:["知识库问答","本地文档检索与来源引用"],
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

async function loadRuntime() {
  const results = await Promise.allSettled([API.get("/health"), API.get("/meta/capabilities"), API.get("/openapi.json"), API.get("/tasks?limit=100")]);
  if (results[0].status === "fulfilled") state.health = results[0].value;
  if (results[1].status === "fulfilled") state.capabilities = results[1].value;
  if (results[2].status === "fulfilled") state.openapi = results[2].value;
  if (results[3].status === "fulfilled") state.history = results[3].value;
  const ok = Boolean(state.health && state.capabilities);
  $("#sideHealthDot").className = `status-dot ${ok ? "ok" : "bad"}`;
  $("#sideHealthText").textContent = ok ? `服务在线 · ${state.health.model_provider}` : "服务不可用";
  $("#runtimeBadge").className = `runtime-badge ${ok ? "ok" : "bad"}`;
  $("#runtimeBadge").innerHTML = `<i></i>${ok ? `${state.health.model_provider} · ${state.capabilities.tools.length} tools` : "服务离线"}`;
}

function capabilityRows() {
  const routes = {file_open:"files",knowledge_query:"knowledge",reminder_create:"reminders",todo_manage:"todos",schedule_manage:"schedule",text_polish:"text",meeting_process:"meetings"};
  return (state.capabilities?.tools || []).map(tool => {
    const label = toolLabels[tool.name] || [tool.name,tool.description];
    return `<a class="module-row" href="#${routes[tool.name] || "console"}"><span class="module-icon">${esc(tool.name.slice(0,2).toUpperCase())}</span><span><b>${esc(label[0])}</b><small>${esc(label[1])}</small></span><span class="risk ${tool.risk_level.toLowerCase()}">${tool.risk_level} · ${tool.data_level}</span></a>`;
  }).join("");
}
function renderOverview() {
  const counts = state.history.reduce((acc,t) => (acc[t.state]=(acc[t.state]||0)+1,acc),{});
  const endpoints = Object.values(state.openapi?.paths || {}).reduce((n,item) => n + Object.keys(item).filter(k => ["get","post","put","patch","delete"].includes(k)).length,0);
  pageRoot.innerHTML = header("OPERATIONS","Agent 操作台","所有主要能力、风险闸门、运行态与接口契约都在这里显式可见。",`<button class="button" id="refreshOverview">刷新状态</button><a class="button primary" href="#api-lab">运行接口体检</a>`)+
  `<section class="metrics"><div class="metric"><small>已注册能力</small><strong>${state.capabilities?.tools?.length ?? "—"}</strong><em>预期 7 个工具</em></div><div class="metric"><small>HTTP 操作</small><strong>${endpoints || "—"}</strong><em>来自 OpenAPI</em></div><div class="metric"><small>当前会话任务</small><strong>${state.history.length}</strong><em>隔离任务账本</em></div><div class="metric"><small>待人工确认</small><strong>${counts.awaiting_confirmation || 0}</strong><em>R2 / R3 闸门</em></div></section>`+
  `<div class="grid-2"><section class="panel span-2"><header class="panel-head"><div><h3>七阶段执行链</h3><p>每个任务都会穿过同一条可审计管线</p></div></header>${rail()}</section><section class="panel"><header class="panel-head"><div><h3>功能入口</h3><p>7 个主要能力均有独立测试页</p></div></header><div class="module-list">${capabilityRows() || `<div class="empty-state compact">能力清单未加载</div>`}</div></section>`+
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
  `<div class="grid-2"><section class="panel"><header class="panel-head"><div><h3>自然语言任务</h3><p>适合探索跨模块表达和路由边界</p></div></header><div class="panel-body"><form id="consoleForm">${field("consoleText","任务内容","textarea","例如：查询产品保修政策，给出来源")}${presets(["查询产品保修政策并给出来源","查找项目周报","提醒我30分钟后检查服务","添加待办 提交接口测试报告，高优先级","今天下午有什么安排","总结这段：本季度完成了三个项目"],"consoleText")}<div class="form-actions"><small>Enter 换行；点击按钮提交</small><button class="button primary">提交任务</button></div></form></div></section>${panel("路由说明","输入会经过意图识别与 Schema 校验",subfeatures([["意图识别","映射到 7 个已注册工具"],["参数补全","缺少关键字段时暂停确认"],["数据分级","按 D0–D3 识别敏感度"],["风险判定","按 R0–R3 决定是否确认"],["端云路由","根据数据与资源选择执行位置"],["审计记录","全过程留下可验证事件"]]))}<div id="liveTaskArea" class="span-2"></div></div>`;
  bindPresets(); $("#consoleForm").onsubmit = async e => { e.preventDefault(); await submitTask($("#consoleText").value.trim()); };
  if (state.currentTask) renderLiveTask(state.currentTask);
}

function renderKnowledge() { featureShell({eyebrow:"KNOWLEDGE · R0 / D2",title:"知识库问答",description:"对授权目录中的 TXT、Markdown、DOCX 文档建立本地索引，并返回带来源的答案。",tool:"knowledge_query",risk:"R0",data:"D2",formTitle:"发起知识检索",formSubtitle:"只读操作，无需人工确认",actions:[["query","问答"]],fields:()=>field("knowledgeQuery","问题","textarea","例如：产品保修期是多久？","full")+presets(["产品保修期是多久？","差旅报销标准是什么？","新员工入职需要做什么？","会议室使用有哪些规则？","设备使用有哪些注意事项？"],"knowledgeQuery"),prompt:()=>`查询知识库：${$("#knowledgeQuery").value.trim()}`,subs:[["多格式索引","TXT / MD / DOCX"],["增量同步","按修改时间更新索引"],["语义召回","本地向量与关键词匹配"],["来源引用","文件名与段落定位"],["范围控制","仅检索授权目录"],["敏感脱敏","索引前执行数据分类"]]}); }
function renderFiles() { featureShell({eyebrow:"FILES · R1 / D1",title:"文件查找",description:"搜索授权目录，展示候选文件；真正打开前要求你明确选择。当前安全配置默认禁用系统打开。",tool:"file_open",risk:"R1",data:"D1",formTitle:"查找文件",formSubtitle:"候选选择会作为显式确认步骤",actions:[["search","搜索并选择"]],fields:()=>field("fileQuery","文件关键词","text","例如：项目周报","full")+presets(["项目周报","周报模板","20260721"],"fileQuery"),prompt:()=>`查找并打开文件：${$("#fileQuery").value.trim()}`,subs:[["目录索引","扫描授权根目录"],["模糊搜索","按文件名、扩展名与目录匹配"],["候选排序","相关度与修改时间排序"],["路径摘要","只展示授权根内相对路径"],["人工选择","多候选时暂停确认"],["安全打开","受 AGENT_FILE_OPEN_ENABLED 控制"]]}); }
function renderReminders() { featureShell({eyebrow:"REMINDERS · R1 / D1",title:"提醒管理",description:"创建、查询、取消、完成或清空本地提醒；批量删除会触发 R3 高风险确认。",tool:"reminder_create",risk:"R1",data:"D1",formTitle:"提醒操作",formSubtitle:"支持中文相对时间和周期表达",actions:[["create","创建"],["query","查询"],["cancel","取消"],["complete","完成"],["delete_all","清空全部"]],fields:a=>a==="create"?field("reminderText","提醒内容","text","检查服务")+field("reminderWhen","提醒时间","text","30分钟后 / 明天下午3点")+presets(["30分钟后","明天下午3点","每周一上午9点"],"reminderWhen"):a==="query"?selectField("reminderScope","查询范围",[["next_7_days","未来 7 天"],["overdue","已过期"]],"full"):a==="delete_all"?`<div class="callout bad">此操作会删除全部提醒。Agent 将暂停在 R3 风险确认，不会直接执行。</div>`:field("reminderId","提醒 ID","number","例如：12","full"),prompt:a=>a==="create"?`${$("#reminderWhen").value.trim()}提醒我${$("#reminderText").value.trim()}`:a==="query"?($("#reminderScope").value==="overdue"?"查询已过期提醒":"查看未来7天提醒"):a==="cancel"?`取消提醒 ${$("#reminderId").value}`:a==="complete"?`完成提醒 ${$("#reminderId").value}`:"删除全部提醒",subs:[["相对时间","分钟、小时、明天、后天"],["周期提醒","每周固定日期时间"],["未来查询","未来 7 天活动提醒"],["过期查询","筛出过期未完成项目"],["状态更新","取消或标记完成"],["批量清空","R3 确认后删除全部"]]}); }
function renderTodos() { featureShell({eyebrow:"TODOS · R1 / D1",title:"待办事项",description:"以稳定 ID 管理个人任务，支持筛选、标签、优先级、截止时间和受控删除。",tool:"todo_manage",risk:"R1",data:"D1",formTitle:"待办操作",formSubtitle:"删除动作会进入风险确认",actions:[["create","创建"],["query","查询"],["update","更新"],["complete","完成"],["delete","删除"]],fields:a=>a==="create"?field("todoTitle","标题","text","提交接口测试报告")+selectField("todoPriority","优先级",[["medium","中"],["high","高"],["low","低"]])+field("todoDue","截止表达","text","明天下午3点（可选）")+field("todoTags","标签","text","测试,发布（可选）"):a==="query"?selectField("todoStatus","状态",[["all","全部"],["pending","待处理"],["in_progress","进行中"],["completed","已完成"]])+field("todoKeyword","标题关键词","text","可选"):a==="update"?field("todoId","待办 ID","number","例如：12")+selectField("todoPriority","新优先级",[["high","高"],["medium","中"],["low","低"]]):field("todoId","待办 ID","number","例如：12","full"),prompt:a=>{if(a==="create")return `添加待办 ${$("#todoTitle").value.trim()}，${$("#todoPriority").value==="high"?"高":$("#todoPriority").value==="low"?"低":"中"}优先级${$("#todoDue").value.trim()?`，截止${$("#todoDue").value.trim()}`:""}${$("#todoTags").value.trim()?`，标签${$("#todoTags").value.trim()}`:""}`;if(a==="query")return `${$("#todoStatus").value==="all"?"查看":`查看${$("#todoStatus").selectedOptions[0].text}`}待办${$("#todoKeyword").value.trim()?`，标题包含${$("#todoKeyword").value.trim()}`:""}`;if(a==="update")return `更新待办 ${$("#todoId").value} 为${$("#todoPriority").selectedOptions[0].text}优先级`;return `${a==="complete"?"完成":"删除"}待办 ${$("#todoId").value}`;},subs:[["优先级","高 / 中 / 低"],["标签","最多 20 个分类标签"],["截止时间","中文时间表达解析"],["组合查询","状态、标签、标题、日期范围"],["定点更新","按稳定 ID 修改字段"],["受控删除","删除前执行风险确认"]]}); }
function renderSchedule() { featureShell({eyebrow:"SCHEDULE · R1 / D1",title:"日程管理",description:"创建一次性或重复日程，按时间范围检索，并以稳定 ID 取消。",tool:"schedule_manage",risk:"R1",data:"D1",formTitle:"日程操作",formSubtitle:"重复日程支持每日、每周、每月",actions:[["create","创建"],["query","查询"],["cancel","取消"]],fields:a=>a==="create"?field("scheduleTitle","标题","text","项目例会")+field("scheduleStart","开始时间","text","明天下午2点")+field("scheduleEnd","结束时间","text","明天下午3点（可选）")+field("scheduleLocation","地点","text","A-301（可选）")+selectField("scheduleRepeat","重复",[["none","不重复"],["daily","每天"],["weekly","每周"],["monthly","每月"]])+field("scheduleNotice","提前提醒分钟","number","15"):a==="query"?selectField("scheduleRange","时间范围",[["today","今天"],["tomorrow","明天"],["this_week","本周"],["next_week","下周"]])+field("scheduleKeyword","标题关键词","text","可选"):field("scheduleId","日程 ID","number","例如：12","full"),prompt:a=>a==="create"?`创建日程 ${$("#scheduleStart").value.trim()}${$("#scheduleTitle").value.trim()}${$("#scheduleEnd").value.trim()?`，结束${$("#scheduleEnd").value.trim()}`:""}${$("#scheduleLocation").value.trim()?`，地点${$("#scheduleLocation").value.trim()}`:""}${$("#scheduleRepeat").value!=="none"?`，${$("#scheduleRepeat").selectedOptions[0].text}重复`:""}${$("#scheduleNotice").value?`，提前${$("#scheduleNotice").value}分钟提醒`:""}`:a==="query"?`${$("#scheduleRange").selectedOptions[0].text}有什么安排${$("#scheduleKeyword").value.trim()?`，标题包含${$("#scheduleKeyword").value.trim()}`:""}`:`取消日程 ${$("#scheduleId").value}`,subs:[["一次性日程","标题、起止时间、地点"],["周期规则","每日 / 每周 / 每月"],["星期组合","每周多工作日安排"],["提前通知","0–1440 分钟"],["范围查询","今天、明天、本周、下周、自定义"],["取消日程","按稳定 ID 风险确认"]]}); }
function renderText() { featureShell({eyebrow:"TEXT · R1 / D1",title:"文本处理",description:"在不发送内容的前提下完成润色、总结、语气调整和草拟，并保护日期、金额、电话等事实。",tool:"text_polish",risk:"R1",data:"D1",formTitle:"处理文本",formSubtitle:"MVP 只生成文本，不连接外部发送器",actions:[["polish","润色"],["summarize","总结"],["tone_adjust","语气调整"],["draft","草拟"]],fields:a=>(a==="tone_adjust"?selectField("textTone","目标语气",[["formal","正式"],["casual","轻松"]],"full"):"")+field("textInput","原始内容","textarea","输入需要处理的文本","full")+presets(["项目将在2026年8月1日上线，预算为300万元。","本季度完成了三个项目，分别覆盖知识库、工作流和接口验证。","请尽快提交材料。"],"textInput"),prompt:a=>`${a==="polish"?"润色":a==="summarize"?"总结这段":a==="tone_adjust"?`调整为${$("#textTone").value==="formal"?"正式":"轻松"}语气`:"草拟"}：${$("#textInput").value.trim()}`,subs:[["专业润色","错字与语句流畅度"],["内容总结","长文本压缩"],["语气调整","正式 / 轻松"],["内容草拟","从要点生成短文"],["事实保护","日期、金额、电话原样保留"],["发送隔离","确认文本但不向外发送"]]}); }
function renderMeetings() { const root=state.capabilities?.authorized_roots?.files?.[1]||state.capabilities?.authorized_roots?.files?.[0]||""; const sample=root?`${root}\\项目周报_20260721.txt`:""; featureShell({eyebrow:"MEETING · R2 / D2",title:"会议纪要",description:"读取授权 TXT / Markdown 文稿，生成可追溯 Markdown 纪要；处理前必须人工确认。",tool:"meeting_process",risk:"R2",data:"D2",formTitle:"生成会议纪要",formSubtitle:"源文件必须位于授权目录",actions:[["process","处理文稿"]],fields:()=>field("meetingPath","文稿完整路径","text","例如：F:\\data\\meeting.txt","full")+(sample?presets([sample],"meetingPath"):"")+`<div class="callout warn">R2 操作：确认页会展示影响范围，批准后才读取文稿并写入会议纪要目录。</div>`,prompt:()=>`整理会议纪要 ${$("#meetingPath").value.trim()}`,subs:[["格式校验","仅 TXT / MD"],["授权路径","拒绝目录外文件"],["内容脱敏","处理前识别敏感数据"],["结构提取","决策、行动项、责任人"],["可追溯输出","保留源文件元数据"],["Markdown 交付","写入独立纪要目录"]]}); }

async function submitTask(text) {
  if (!text || /[:：]\s*$/.test(text)) { toast("请先填写完整参数", true); return; }
  try {
    const task = await API.post("/tasks", {text}); state.currentTask = task; state.history.unshift(task);
    renderLiveTask(task); selectTask(task); connectTask(task.id); toast(`任务 ${shortId(task.id)} 已提交`);
  } catch (error) { toast(error.message, true); }
}
function connectTask(id) {
  state.eventSources.get(id)?.close(); const source = new EventSource(`/tasks/${id}/events`); state.eventSources.set(id,source);
  source.addEventListener("task", event => { const task=JSON.parse(event.data); updateTask(task); if(terminal.has(task.state)) source.close(); });
  source.onerror = () => { if (!terminal.has(state.currentTask?.state)) toast("状态流暂时中断，浏览器会自动重连",true); };
}
function updateTask(task) {
  state.currentTask=task; const index=state.history.findIndex(t=>t.id===task.id); if(index>=0) state.history[index]=task; else state.history.unshift(task);
  renderLiveTask(task); selectTask(task,false);
}
function resultData(task) { return task?.result?.receipt || task?.result || {}; }
function renderLiveTask(task) {
  const area=$("#liveTaskArea"); if(!area)return; const meta=stateMeta[task.state]||[task.state,0,""]; const result=resultData(task); const output=result.output||{};
  let content=""; if(task.state==="completed") content=output.answer||output.text||result.output_summary||"处理完成"; else if(task.error) content=task.error;
  const sources=output.sources||[];
  area.innerHTML=`<section class="panel task-card"><header class="panel-head"><div><h3><span class="state-pill ${task.state}">${meta[0]}</span> · ${shortId(task.id)}</h3><p class="task-summary">${task.state==="completed"?"任务已通过全部执行阶段":task.context?.intent?`已识别能力：${esc(task.context.intent)}`:"Agent 正在处理任务"}</p></div><button class="button small" data-inspect-task>在检查器中查看</button></header>${rail(task)}${renderConfirmation(task)}${content?`<div class="task-result"><strong>${task.state==="completed"?"执行结果":"错误"}</strong>${esc(content)}${sources.length?`<div class="sources">${sources.map(s=>`<span class="source-chip">${esc(s.file||s.document||"来源")} · ${esc(s.section??s.position??"全文")}</span>`).join("")}</div>`:""}</div>`:""}</section>`;
  $("#miniRail") && ($("#miniRail").innerHTML=rail(task)); $("[data-inspect-task]",area).onclick=()=>openInspector(); bindConfirmation(task,area);
}
function renderConfirmation(task) {
  if(task.state!=="awaiting_confirmation")return""; const data=task.result||{}; const type=data.type; let body="";
  if(type==="missing_fields") body=`<p>${esc(data.message||"请补充缺失参数")}</p>${(data.fields||[]).map(name=>field(`confirm-${name}`,name==="when"?"具体时间":name,"text",name==="when"?"例如：15:00":"请输入内容","full")).join("")}`;
  else if(type==="candidate_confirmation") { const candidates=data.receipt?.output?.candidates||[]; body=`<p>选择一个候选文件后继续：</p>${candidates.map((f,i)=>`<label class="candidate"><input type="radio" name="candidate" value="${esc(f.path)}" ${i===0?"checked":""}><span><b>${esc(f.name)}</b><small>${esc(f.path_summary||f.path)} · ${fmt(f.modified_at)}</small></span></label>`).join("")}`; }
  else { const info=data.confirmation||{}; body=`<p>${esc(info.content||data.message||"此操作需要人工确认")}</p><div>${esc(info.impact||"")}</div>`; }
  return `<div class="confirmation"><h4>人工确认闸门 · ${esc(task.risk_level)}</h4>${body}<div class="form-actions"><button class="button danger small" data-reject>拒绝</button><button class="button primary small" data-confirm>确认并继续</button></div></div>`;
}
function bindConfirmation(task,root) {
  const confirm=$("[data-confirm]",root), reject=$("[data-reject]",root); if(!confirm)return;
  confirm.onclick=async()=>{const data=task.result||{},args={}; if(data.type==="missing_fields") (data.fields||[]).forEach(name=>args[name]=$(`#confirm-${name}`,root)?.value.trim()||""); if(data.type==="candidate_confirmation") args.selected_path=$("input[name=candidate]:checked",root)?.value||""; confirm.disabled=true; try{updateTask(await API.post(`/tasks/${task.id}/confirm`,{approved:true,arguments:args}));}catch(e){toast(e.message,true);confirm.disabled=false;}};
  reject.onclick=async()=>{reject.disabled=true;try{updateTask(await API.post(`/tasks/${task.id}/confirm`,{approved:false,arguments:{}}));}catch(e){toast(e.message,true);reject.disabled=false;}};
}

function selectTask(task, open=true) { state.currentTask=task; renderInspector(); if(open && window.innerWidth<=1180) openInspector(); }
function openInspector(){ $("#inspector").classList.add("open"); }
function closeInspector(){ $("#inspector").classList.remove("open"); }
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
async function renderRoute(){const route=currentRoute(),info=routeInfo[route];$("#pageEyebrow").textContent=info[0];$("#pageTitle").textContent=info[1];$$('[data-route]').forEach(a=>a.classList.toggle("active",a.dataset.route===route));closeNavigation();const renderers={overview:renderOverview,console:renderConsole,knowledge:renderKnowledge,files:renderFiles,reminders:renderReminders,todos:renderTodos,schedule:renderSchedule,text:renderText,meetings:renderMeetings,"api-lab":renderApiLab,tasks:renderTasks};await renderers[route]();pageRoot.focus({preventScroll:true});window.scrollTo(0,0);}
function closeNavigation(){$("#sidebar").classList.remove("open");$("#navBackdrop").hidden=true;$("#menuButton").setAttribute("aria-expanded","false");}

$("#menuButton").onclick=()=>{const open=$("#sidebar").classList.toggle("open");$("#navBackdrop").hidden=!open;$("#menuButton").setAttribute("aria-expanded",String(open));};
$("#navBackdrop").onclick=closeNavigation;$("#inspectorButton").onclick=openInspector;$("#closeInspector").onclick=closeInspector;
$$('[data-inspector-tab]').forEach(button=>button.onclick=()=>{state.inspectorTab=button.dataset.inspectorTab;$$('[data-inspector-tab]').forEach(b=>b.classList.toggle("active",b===button));renderInspector();});
window.addEventListener("hashchange",renderRoute);
window.addEventListener("beforeunload",()=>state.eventSources.forEach(source=>source.close()));

(async function boot(){await loadRuntime();await renderRoute();})();
