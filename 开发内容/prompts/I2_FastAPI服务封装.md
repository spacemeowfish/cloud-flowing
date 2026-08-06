# I2：FastAPI 服务封装

> Phase 3 集成层 | 依赖 I1 | 顺序执行

将此提示词完整复制给 Codex，作为开发任务。

---

## 开发提示词

### 目标
将 Agent Core 封装为 FastAPI HTTP 服务。提供 RESTful API 接口：创建任务、查询任务状态、确认/取消任务、获取审计日志。为后续文字界面和语音界面提供统一的 API 层。

### 判断标准

1. API 端点：POST /tasks（创建）、GET /tasks/{id}（查询）、POST /tasks/{id}/confirm（确认）、POST /tasks/{id}/cancel（取消）、GET /tasks/{id}/audit（审计日志）
2. 请求和响应使用 F1 定义的 Pydantic 模型
3. 支持 Server-Sent Events（SSE）推送任务状态变更
4. API 错误返回统一的 ErrorResponse 格式
5. OpenAPI 文档可通过 /docs 访问

### 证据要求

- 使用 pytest + httpx.AsyncClient 编写 API 集成测试
- 创建任务→查询状态→确认→查看结果，全链路 API 测试通过
- SSE 测试：客户端连接后，任务状态变更在 500ms 内推送
- 错误测试：非法请求返回 422、任务不存在返回 404、权限不足返回 403

### 权限边界

- API 不实现用户认证（由外部认证代理处理），但预留认证中间件接口
- 审计日志 API 只返回当前会话的任务，不允许跨任务查询
- 不通过 API 暴露内部模块的直接调用（如直接调 ModelGateway）

### 停止条件

- 全链路 API 测试通过
- SSE 推送测试通过
- 错误处理测试通过
- OpenAPI 文档完整且可访问

### 完成边界

`api/server.py`、`api/routes.py`、`api/middleware.py`。FastAPI 应用在 `api/__init__.py` 中创建。

---

## 代码审查提示词

**质量**：异常处理的中间件是否覆盖了所有 Agent 异常类型、SSE 连接断开后是否正确清理

**性能**：并发请求下的任务隔离、SSE 连接数的上限控制

**复用性**：路由是否模块化（后续新增 API 版本时不影响现有路由）
