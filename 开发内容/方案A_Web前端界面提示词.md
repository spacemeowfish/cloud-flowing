# 方案 A：Agent Platform MVP 单页 Web 界面

> 零依赖单 HTML 文件，聊天式交互，SSE 实时状态流，直接对接已有 FastAPI 后端

将此提示词完整复制给 Codex，作为开发任务。

---

## 开发提示词

### 目标
编写一个独立的 index.html 文件，作为 Agent Platform MVP 的 Web 前端界面。用户输入自然语言中文请求，界面通过 SSE 实时展示任务 7 步执行流程（接收→理解→校验→权限→路由→执行→交付），并支持确认交互（候选选择、风险确认、参数补填）。零外部依赖，纯原生 HTML/CSS/JS，放置于 FastAPI 的 static/ 目录即可通过 http://127.0.0.1:8000/ 访问。

### 判断标准

1. **聊天式布局**：底部输入框 + 发送按钮，消息以聊天气泡形式向上滚动，用户消息和系统状态卡片交替排列
2. **SSE 实时更新**：创建任务后通过 EventSource 连接 /tasks/{id}/events，每个状态变更即时渲染为进度卡片，不使用轮询
3. **7 步流程可视化**：任务创建后显示步骤进度条（理解→校验→权限→路由→执行→交付），当前步骤高亮，已完成打勾，失败标红
4. **确认交互**：当任务进入 awaiting_confirmation 状态时，显示内联确认面板——多候选列表可选、风险提示可确认/取消、缺失参数可填写
5. **审计回放**：每个任务卡片右上角有「审计」按钮，点击展开该任务的完整审计事件时间线
6. **中文无乱码**：所有请求的 Content-Type 头正确设置 UTF-8，从 API 返回的中文内容正确渲染
7. **响应式**：在 1920px 桌面和 375px 窄屏上均可正常使用

### 证据要求

- 打开页面后能看到欢迎语和输入框
- 输入「帮我润色这段话：今天天气不错」→ 发送 → 实时看到状态从 understanding 流转到 completed → 显示润色结果
- 输入「整理会议纪要」→ 发送 → 进入 awaiting_confirmation → 显示 source_path 输入框 → 填入路径确认 → 任务继续执行
- 点击任意任务的「审计」→ 展开 7 条审计事件，每条显示时间、类型、决策、成功/失败
- 在 Chrome DevTools Network 面板中确认 SSE 连接正常工作、无 404 或 500 错误
- 页面首次加载时自动 GET /health 并在页脚显示服务状态（在线/离线 + 模型类型）

### 权限边界

- 不引入任何 npm 包、CDN 资源或前端框架（包括 Tailwind/Bootstrap CDN 也禁止）
- 所有 CSS 写在 `<style>` 标签内，所有 JS 写在 `<script>` 标签内
- 不修改后端代码（只读 API）
- API 基础地址从 `window.location.origin` 自动获取，不硬编码
- 只调用已有端点：POST /tasks、GET /tasks/{id}、POST /tasks/{id}/confirm、POST /tasks/{id}/cancel、GET /tasks/{id}/audit、GET /tasks/{id}/events、GET /health

### 停止条件

- 5 种意图各测试一次，全部在界面中正确展示完整流程
- 确认流程测试：会议纪要缺参数 → 显示补填面板 → 填入后继续 → 完成
- 取消流程测试：任务执行中点击取消 → 状态变为 cancelled → 审计日志记录取消原因
- 审计回放测试：展开后 7 个事件时间戳递增、类型完整
- 页面在 Firefox 和 Chrome 上均能正常使用

### 完成边界

交付单个文件 `static/index.html`。文件大小不超过 15KB（压缩前）。FastAPI app 需增加 `StaticFiles` 挂载以服务此文件，在后端代码中只加一行：

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

---

### 界面结构参考

```
┌─────────────────────────────────────────┐
│  Agent Platform MVP                     │
│  ─────────────────────────────────────  │
│                                         │
│  [系统] 你好，我是本地 Agent。          │
│         可以帮你打开文件、查知识库、     │
│         管理提醒、润色文本、整理会议纪要。│
│                                         │
│  [用户] 帮我打开项目周报                 │
│                                         │
│  [系统] ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │
│  理解中 → 校验中 → 权限中 → 路由中...   │
│                                         │
│  [系统] 找到 3 个候选文件：              │
│  ○ 项目周报_20260721.docx               │
│  ○ 项目周报_20260714.docx               │
│  ○ 项目周报模板.docx                    │
│  [确认打开] [取消]                      │
│                                         │
│  [系统] ✅ 已打开 项目周报_20260721.docx │
│         [查看审计]                      │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │ 输入您的请求...              [发送]│   │
│  └──────────────────────────────────┘   │
│  服务状态 ●在线 | 模型: mock             │
└─────────────────────────────────────────┘
```

### 状态展示规范

| 任务状态 | 进度条 | 图标 | 文案 |
|---|---|---|---|
| received | 1/7 | ⬇ | 已收到请求 |
| understanding | 2/7 | 🧠 | 正在理解意图... |
| validating | 3/7 | ✓ | 正在校验参数 |
| awaiting_confirmation | 暂停 | ⚠ | 需要您的确认 |
| executing | 4/7 | ⚡ | 正在执行... |
| delivering | 5/7 | 📦 | 准备交付结果 |
| waiting_network | 暂停 | 🌐 | 等待网络恢复 |
| completed | 7/7 | ✅ | 任务已完成 |
| failed | — | ❌ | 任务失败 |
| cancelled | — | ⊘ | 已取消 |

### SSE 处理逻辑

```javascript
const es = new EventSource(`/tasks/${taskId}/events`);
es.addEventListener('task', (e) => {
  const task = JSON.parse(e.data);
  updateTaskCard(taskId, task);  // 更新进度条、状态图标、结果内容
  if (task.state === 'awaiting_confirmation') {
    showConfirmationPanel(taskId, task.result);  // 渲染确认面板
  }
  if (['completed', 'failed', 'cancelled'].includes(task.state)) {
    es.close();  // 终态断开 SSE
  }
});
```

### 确认面板逻辑

根据 `task.result.type` 渲染不同的交互组件：
- `missing_fields`：显示缺失字段列表 + 输入框 + 「补充并确认」按钮
- `risk_confirmation`：显示风险等级和说明 + 「确认执行」「取消」按钮
- `candidate_confirmation`：显示候选列表（单选）+ 「确认」「取消」按钮

确认时调用 `POST /tasks/{id}/confirm`，取消时调用 `POST /tasks/{id}/cancel`。

### 审计面板逻辑

点击「审计」按钮 → 调用 `GET /tasks/{id}/audit` → 在任务卡片下方展开折叠面板，显示时间线：

```
14:05:42  input_received        → ✅
14:05:42  model_output          → intent=file_open
14:05:42  schema_validated      → valid
14:05:42  policy_decided        → allowed
14:05:42  routing_decided       → local
14:05:42  tool_called           → ✅ file_search
14:05:42  result_delivered      → ✅
```

---

## 代码审查提示词（质量）

审查 index.html，检查项：
1. EventSource 的连接断开后是否有重连逻辑（浏览器内置重连即可，但要确保终态时主动 close）
2. 确认面板在 SSE 推送新状态后是否正确刷新（不残留旧面板）
3. 多个并发任务时，每个任务的 SSE 连接是否正确隔离
4. 中文内容在 DOM 中渲染是否正确（检查 meta charset）
5. JSON.parse 是否有 try-catch 保护

---

## 代码审查提示词（性能）

审查 index.html，检查项：
1. DOM 操作是否批量进行（避免每个状态变更都触发 reflow）
2. 审计面板的折叠动画是否使用 CSS transition 而非 JS 动画
3. 滚动到底部的逻辑是否避免了强制同步布局
4. 长时间运行后 DOM 节点是否会无限增长（旧任务卡片是否保留上限）

---

## 代码审查提示词（复用性）

审查 index.html，检查项：
1. API 调用是否统一封装为 `api.post()` / `api.get()` 函数
2. 任务卡片的渲染逻辑是否与数据处理逻辑分离
3. 状态→图标→文案的映射是否集中在一个配置对象中（方便后续加新状态）
