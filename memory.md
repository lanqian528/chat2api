# 共享记忆

最后更新：2026-04-17
编码：UTF-8 with BOM（为 Windows 终端和编辑器兼容性显式设置）
维护方式：任何线路开始动手前先读本文件；完成一个可交付点后立即回写本文件。

## 主调度策略

- 主调度目标：先提升稳定性、兼容性、可观测性和资源控制，再考虑更大范围的架构调整。
- 当前协作文档：高层事实记录在 `memory.md`，逐线交接记录在 `handoff.md`。
- 短期优先级：A/B 联合稳定模型与 API 兼容，C/D 联合稳定反代与重试。
- 中期优先级：统一请求上下文、错误映射合同、缓存/状态存储和结构化日志。
- 长期方向：如果要继续降低运行风险，优先考虑迁移到官方 API/正式接入方案。

## 合规边界

- 可以做：缓存、限流、并发保护、退避、熔断、日志、指标、错误语义收敛、协议兼容修复、状态存储改造。

## 目标

- 为当前仓库内的多条并行工作线提供统一上下文。
- 记录事实、边界、风险和当前认领，减少重复实现与相互覆盖。
- 本文件只记录协作信息，不存放任何密钥、Token、Cookie 或敏感配置值。

## 项目概览

- 项目类型：基于 FastAPI 的 ChatGPT -> OpenAI 兼容 API 代理，同时支持官网镜像网关能力。
- 入口文件：`app.py`
- API 主入口：`api/chat2api.py`
- 核心会话编排：`chatgpt/ChatService.py`
- 模型映射与模型辅助逻辑：`api/models.py`
- 反向代理主逻辑：`gateway/reverseProxy.py`
- 重试策略：`utils/retry.py`
- 运行时配置：`utils/configs.py`
- 网关相关逻辑：`gateway/*.py`
- 模板与静态上下文：`templates/*`

## 当前结构认知

### 事实

- `app.py` 负责创建 FastAPI 应用、注册 CORS，并根据 `ENABLE_GATEWAY` 决定是否加载 `gateway/*` 路由。
- `api/chat2api.py` 暴露 `/v1/chat/completions`、`/v1/models`、`/tokens` 等接口，并负责调度 `ChatService`。
- `chatgpt/ChatService.py` 负责请求上下文初始化、鉴权、模型选择、上游会话准备与发送。
- `utils/configs.py` 负责读取环境变量；当前已存在 `CHECK_MODEL` 与 `HISTORY_DISABLED` 配置项。
- `gateway/backend.py`、`gateway/v1.py`、`gateway/reverseProxy.py` 承担官网镜像侧的反向代理与响应修正。
- `utils/retry.py` 是 API 路径上的通用重试入口，行为变化会影响多个调用链。

### 建议并行工作面

- 线路 A：模型解析、模型可用性校验、模型错误语义一致性。
- 线路 B：OpenAI 兼容 API 路由、请求/响应格式稳定性。
- 线路 C：官网镜像网关、反向代理行为、上游错误映射。
- 线路 D：重试策略、瞬时故障恢复、异常放大控制。
- 线路 E：配置、部署、文档与环境变量说明。

## 当前已纳入的本地进行中改动

### 线路 A：模型解析与上游模型校验

涉及文件：`api/models.py`、`chatgpt/ChatService.py`

当前未提交改动的意图如下：

- 抽取 `MODEL_REQUEST_RULES`，统一维护“外部模型名 -> 上游请求模型名”的映射规则。
- 新增 `get_response_model(origin_model)`，统一响应模型名回写逻辑。
- 新增 `resolve_request_model(origin_model)`，把请求模型解析、`gizmo` 识别、动态模型判定集中到一个地方。
- 新增 `extract_model_slugs(models_payload)`，用于从上游 `/backend-api/models` 返回中提取可用模型集合。
- 在 `ChatService` 中引入 `resolve_auth_context()` 与 `initialize_request_context()`，把原本耦合在 `set_dynamic_data()` 中的职责拆开。
- 增加 `model_not_found()`、`fetch_available_models()`、`validate_model_access()`，统一 404 语义并增加模型可用性校验。
- 增加按 `host_url + account_id + token_hash` 划分的模型缓存，TTL 为 300 秒。

当前判断：

- 这是一次明显的“去重复 + 规则下沉 + 职责拆分”的重构，符合 DRY / SRP / KISS。
- 该改动会直接影响模型选择、鉴权上下文初始化、上游请求前校验，属于核心链路改动。

### 线路 B：OpenAI 兼容 API 路由补强

涉及文件：`api/chat2api.py`

当前未提交改动的意图如下：

- 给 `process()` 增加异常关闭与统一错误处理，避免准备发送阶段异常时泄漏客户端资源。
- 新增 `parse_bool_query()`，统一布尔查询参数解析。
- 新增 `format_models_response()`，以 OpenAI 风格返回模型列表。
- 新增 `/v1/models` 路由，复用 `ChatService.fetch_available_models()` 暴露上游模型列表。
- 路由层显式接入 `history_disabled` 作为模型列表请求的默认值。

当前判断：

- 这是围绕“模型可见性”补齐 OpenAI 兼容面的改动，和线路 A 存在中等耦合。
- 如果后续继续扩展 `/v1/models` 兼容性，优先在该文件收口，不要把响应格式散落到 `ChatService`。

### 线路 C：官网镜像反向代理错误语义收敛

涉及文件：`gateway/reverseProxy.py`、`gateway/backend.py`

当前未提交改动的意图如下：

- 在内部请求块中单独捕获 `HTTPException`，关闭客户端后按原状态继续抛出。
- 对未知异常增加日志 `Reverse proxy failed for {path}`。
- 对通用异常统一返回 `502 Upstream request failed`，避免把底层异常直接泄露到调用方。
- 修复 `gateway/backend.py` 中两处 `token.startswith` 被误写为方法对象判断的问题。
- 修复 `check_account` 在缺少 `Authorization` 请求头时直接触发 500 的问题。

当前判断：

- 这是一次“资源清理 + 错误语义收敛”的稳定性修正。
- 该改动会直接影响网关错误码、观测性和调用方重试行为，属于网关主链路改动。

### 线路 D：重试策略收敛与退避

涉及文件：`utils/retry.py`

当前未提交改动的意图如下：

- 增加 `RETRYABLE_STATUS_CODES`，把可重试状态码限制为 `408/500/502/503/504`。
- 增加 `get_retry_delay()`，采用指数退避，基础延迟 0.5 秒，最大 4 秒。
- `async_retry()` 与 `retry()` 改为只在可重试状态码上重试，其余异常立即抛出。
- 同步补充异步/同步两条路径的等待逻辑，避免无差别快速重试。

当前判断：

- 这是一次“限制盲目重试 + 控制重试节奏”的通用基础设施改动，符合 KISS / YAGNI。
- 该文件属于横切关注点，一旦继续修改，必须同步考虑 API 路径与网关路径的影响。

## 当前协作边界

### 已被占用/应谨慎操作的文件

- `api/models.py`
- `chatgpt/ChatService.py`
- `api/chat2api.py`
- `gateway/reverseProxy.py`
- `gateway/backend.py`
- `utils/retry.py`

说明：

- 上述文件均已有本地未提交改动；后续任何线路进入前都必须先读最新内容，再决定是否继续叠加修改。
- 线路 A 与线路 B 通过 `/v1/models` 和 `fetch_available_models()` 形成耦合。
- 线路 C 与线路 D 在“上游失败 -> 错误码 -> 是否重试”的路径上存在耦合。

### 推荐文件归属

- 模型相关：`api/models.py`、`chatgpt/ChatService.py`
- API 路由相关：`api/chat2api.py`
- 网关相关：`gateway/backend.py`、`gateway/v1.py`、`gateway/chatgpt.py`、`gateway/login.py`、`gateway/reverseProxy.py`
- 重试/容错相关：`utils/retry.py`
- 配置与部署：`utils/configs.py`、`.env.example`、`README.md`、`docker-compose*.yml`、`Dockerfile`

## 当前风险与待验证项

- `README.md` 在当前 PowerShell 输出中出现乱码，推测是终端编码展示问题；不要基于控制台乱码直接改写文档内容。
- `memory.md` 已按 UTF-8 with BOM 保存，以提高 Windows 本地打开时的稳定性；如果终端仍乱码，优先检查控制台输出编码，而不是重写文件内容。
- `/v1/models` 依赖上游 `/backend-api/models`；需要验证不同账户态、代理态、异常态下的返回是否稳定。
- `resolve_request_model()` 的默认回退策略已从“未知模型强制回退到 `gpt-4o`”转向“保留原模型并标记为动态模型”；这会影响未知模型名的兼容性，应重点回归。
- `gizmo` 模型路径当前绕过模型可用性校验；如后续要增强校验，需要确认 GPTs 的真实上游约束。
- `gateway/reverseProxy.py` 现在把通用异常统一映射为 502；需要确认上层调用链是否会因此触发新的重试分支。
- `utils/retry.py` 现在只重试部分状态码；需要确认历史上依赖“所有 HTTPException 都重试”的调用场景是否存在行为变化。
- 当前缓存 Key 使用 `host_url + account_id + token_hash`；如果后续多网关/多账户轮询策略变化，需要重新确认缓存粒度是否足够。

## 协作规则

- 开始工作前：先读本文件，再读自己要改的目标文件。
- 开始修改时：先在“当前认领”中登记负责范围。
- 修改完成后：同步更新“当前状态 / 风险 / 下一步”。
- 不要在本文件记录敏感信息、真实 Token、代理账号、Cookie、私有域名。
- 避免多条线同时修改同一文件；若不可避免，先在本文件明确主导线路。

## 当前认领

- 线路 A（模型解析与校验）：进行中；主文件 `api/models.py`、`chatgpt/ChatService.py`
- 线路 B（API 路由与 `/v1/models`）：进行中；主文件 `api/chat2api.py`
- 线路 C（网关反向代理错误语义）：进行中；主文件 `gateway/reverseProxy.py`
  补充：`gateway/backend.py` 已纳入该线
- 线路 D（重试策略与退避）：进行中；主文件 `utils/retry.py`
- 线路 E（配置/部署/文档）：未认领

## 下一步建议

- 先做一轮 A + B 联合回归：验证模型选择、未登录访问、`gizmo`、未知模型名、`CHECK_MODEL=true`、`/v1/models` 返回结构。
- 再做一轮 C + D 联合回归：验证上游 502、超时、瞬时 500/503 时的反代错误码与重试次数是否符合预期。
- 其余线路如需并行，优先避开上面 5 个已占用文件，先处理文档、部署或其他网关路由。
- 如果后续要长期并行协作，建议新增 `handoff.md` 专门记录每条线的交接事项，本文件只保留高层事实。
