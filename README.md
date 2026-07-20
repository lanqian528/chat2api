# CHAT2API

🤖 一个简单的 ChatGPT TO API 代理

🌟 无需账号即可使用免费、无限的 `GPT-3.5`

💥 支持 AccessToken 使用账号，支持 `O3-mini/high`、`O1/mini/Pro`、`GPT-4/4o/mini`、`GPTs`

🔍 回复格式与真实 API 完全一致，适配几乎所有客户端

👮 配套用户管理端[Chat-Share](https://github.com/h88782481/Chat-Share)使用前需提前配置好环境变量（ENABLE_GATEWAY设置为True，AUTO_SEED设置为False）

---

## ✨ nanashiwang 分支新特性

> 本分支在上游基础上做了大量工程化增强，**适合生产部署**。完整说明见 [`docs/FEATURES.md`](docs/FEATURES.md)。

### 一键部署（零交互）

```bash
curl -fsSL https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/install.sh | bash
```

脚本默认部署多实例编排面板：装 Docker → 下载编排脚本 → 启动 orchestrator → 安装 `chat2api` 管理命令 → 打印访问地址。

### 新增能力一览

| 能力 | 说明 | 文档 |
|---|---|---|
| 🛡️ **Antiban 风控层** | IP-账号粘性桶 / 账号冷却 / 地域一致性 / 熔断自愈 | [FEATURES#1](docs/FEATURES.md#1-antiban-风控规避层) |
| 🍪 **Harvester 采集** | UI 上粘贴 chatgpt.com session cookie 自动验证+导入 | [COOKIE_HARVEST](docs/COOKIE_HARVEST.md) |
| 📂 **文件上传导入** | .txt / .json 自动解析，预览后确认导入 | [FEATURES#3](docs/FEATURES.md#3-管理后台增强) |
| 📝 **系统日志 UI** | 实时轮询 / 级别筛选 / 关键字搜索 / 一键下载 | [FEATURES#4](docs/FEATURES.md#4-系统日志-ui) |
| 🔐 **安全加固** | IP 白名单 / HttpOnly / CSRF / 密码隔离 / CF 指引 | [SECURITY](docs/SECURITY.md) |
| 🔄 **UI 代理热加载** | 添加/删除代理即时生效，不需重启 | [FEATURES#3](docs/FEATURES.md#3-管理后台增强) |
| 🎯 **新版 Token 识别** | 支持 `rt_*` 新格式 + `sess-*` SessionToken + chat_refresh 现代化 | [FEATURES#6](docs/FEATURES.md#6-新版-token-支持) |
| 🧩 **一容器一账号编排** | `deploy/multi/` 提供生成器 + nginx 路径分发 + orchestrator 面板，N 个账号 = N 个隔离容器 | [部署：多实例](#多实例一容器一账号) |
| 🔗 **LibreChat 会话续接** | request body 携带 `librechat_conversation_id` 即可让同窗口在 ChatGPT 端续会话（节省 token + 用上账号原生记忆） | [LibreChat 集成](#librechat--new-api-集成) |

### 核心运维流程

```
1. 一键部署 (install.sh)
       ↓
2. 登录管理后台 (URL 从部署脚本最后输出)
       ↓
3. 配置 IP 白名单 (SECURITY.md)        ← 强烈建议
       ↓
4. (可选) 代理与路由 → 添加住宅代理
       ↓
5. 账号采集 Harvester → 🍪 粘贴 Cookie  ← 主流程
       ↓
6. 开始使用 /v1/chat/completions
       ↓
7. 日常升级 → `chat2api update`
       ↓
8. Cookie 过期 (数月后) → 重抓并替换
```

### Cookie 抓取快速链接

需要在**和 chat2api 出口 IP 相似的地区**登录 chatgpt.com 抓 cookie。完整指南（含 SSH 隧道技巧）见 [`docs/COOKIE_HARVEST.md`](docs/COOKIE_HARVEST.md)。

速抓命令：
```javascript
// 浏览器登录 chatgpt.com 后，F12 Console 执行
document.cookie.split(';').filter(x=>x.includes('session-token')).join('; ')
```

---

## LibreChat / New-API 集成

> 适用场景：`LibreChat → New-API → chat2api → ChatGPT` 链路下，希望**同一对话窗口在 ChatGPT 服务端续会话**（账号原生 Memory 自动累积，每次只发最新一条 user message 节省 token）。

### 工作原理

```
[LibreChat 窗口 X]                            [chat2api]
  messages = [system, u1, a1, u2, a2, u3]      ① 看到 librechat_conversation_id
  body 含 librechat_conversation_id            ② 查 sqlite 映射 → ChatGPT conv_id
        ↓                                      ③ 命中：注入 conversation_id +
[New-API Channel Affinity]                       parent_message_id，messages 截短
  按 lc_conv_id 路由到固定渠道                 ④ 转发 ChatGPT
        ↓                                     ⑤ 嗅探响应里的 conv_id 回写映射
[chat2api 实例 K]
        ↓
[ChatGPT 服务端] 续接 conv，自动用上账号原生记忆
```

### 三段配置（chat2api 已默认开启）

#### 1. LibreChat（`librechat.yaml`，零代码）

```yaml
endpoints:
  custom:
    - name: "chat2api"
      apiKey: "${NEWAPI_KEY}"
      baseURL: "https://your-newapi/v1"
      addParams:
        librechat_conversation_id: "{{LIBRECHAT_BODY_CONVERSATIONID}}"
        librechat_user_id: "{{LIBRECHAT_USER_ID}}"
      models:
        default: ["gpt-5-5", "gpt-5", "gpt-4o", "gpt-4o-mini", "o1-preview", "o3-mini"]
```

#### 2. New-API Channel Affinity（后台 UI 配置）

```json
{
  "enabled": true,
  "rules": [{
    "name": "librechat_conv_sticky",
    "model_regex": ["gpt.*", "o1.*", "o3.*"],
    "key_sources": [{"type": "gjson", "path": "librechat_conversation_id"}],
    "ttl_seconds": 86400,
    "switch_on_success": true,
    "skip_retry_on_failure": false
  }]
}
```

#### 3. chat2api（默认开启，对裸 OpenAI 客户端无影响）

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `ENABLE_SESSION_STICKY` | `true` | 总开关 |
| `SESSION_TTL_DAYS` | `30` | 多少天未活跃自动清理映射 |
| `SESSION_LC_FIELD` | `librechat_conversation_id` | request body 中携带 LibreChat conversationId 的字段名 |
| `SESSION_TRIM_TO_LAST_USER` | `true` | 命中映射时是否把 messages[] 截到只含最后一条 user（依赖 ChatGPT 服务端续历史） |

数据存储：`/app/data/sessions.db`（SQLite，跟随实例数据卷）。
映射失效（ChatGPT 端 conv 被删）→ 自动清理 + `async_retry` 重新建对话。

### 验证

```bash
# 在某 chat2api 实例容器内
docker exec -it c2a-<slug> sqlite3 /app/data/sessions.db \
  "SELECT * FROM lc_session_map LIMIT 5;"

# 查看命中日志
docker logs c2a-<slug> | grep session_sticky
# 应有:  [session_sticky] hit lc=lc-uuid... → cv=cv-XXX...
```

---

## 多实例（一容器一账号）

> 适用场景：N 个 ChatGPT 账号 + 多用户并发；通过 `deploy/multi/` 把每个账号编排到独立容器（独立代理 / 独立指纹 / 独立 cookie 卷），单账号被风控时其他账号不连坐。

### 一句话部署

```bash
curl -fsSL https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/install.sh | bash
```

初始化完成后，脚本会直接输出编排面板入口和密码，然后打开：

```text
http://<vps>:60403/orchestrator/
```

如果你已经用一键脚本装了单实例，请走迁移流程，避免 60403 端口冲突：

```bash
chat2api migrate prep
chat2api migrate apply
```

进入面板后点「新增账号」，填写 `slug`、代理和备注即可；不需要手动编辑 `accounts.csv`。

`accounts.csv` 仍然保留给批量导入/脚本化部署使用。

### 统一调用入口

多实例会额外暴露一个统一 OpenAI 兼容入口，由 Orchestrator 自动均衡到各个账号容器：

```text
Base URL: http://<vps>:60403/v1
API Key:  编排面板右上角「统一 API」查看
```

路由策略：

- 无会话键：轮询分配到不同容器
- 有 `librechat_conversation_id` / `conversation_id` / `X-Chat2API-Affinity`：固定到同一容器
- Orchestrator 会把统一 Key 转成目标容器自己的 `AUTHORIZATION`

### 已默认应用的工程加固（`deploy/multi/generate.py`）

| 类别 | 项 | 默认 |
|---|---|---|
| 风控 | `ENABLE_ANTIBAN` | `true` |
| 风控 | `STRICT_IP_BINDING` | `true` |
| 风控 | `BUCKET_MAX_ACCOUNTS_PER_IP` | `1` |
| 风控 | 账号级冷却 (`ACCOUNT_MIN_INTERVAL_SECONDS`) | `0`（一容器一账号无需自限速） |
| 风控 | 429/403 熔断退避 | 1800/3600s |
| 安全 | `cap_drop: [ALL]` + `no-new-privileges` | ✅ |
| 资源 | `mem_limit / cpus / pids_limit` | 512m / 0.5 / 200 |
| 续会话 | `ENABLE_SESSION_STICKY` | `true` |

### 从单实例迁移到多实例

```bash
chat2api migrate prep                 # 备份 + 生成 accounts.csv 模板（安全）
chat2api migrate apply                # 停单 + 启多（需输 yes 确认）
# 不满意可回滚：
chat2api migrate rollback ~/chat2api.backup-YYYYMMDD-HHMMSS
```

迁移完成后打开 orchestrator 面板管理账号；如需批量预置账号，再编辑 `~/chat2api/deploy/multi/accounts.csv`。

---

## 功能总览

### OpenAI 兼容接口

- 流式 / 非流式响应
- 模型支持：免登录 `GPT-3.5`、`GPT-4 / 4o / 4o-mini`、`GPT-5 / 5-mini / 5-thinking / 5-pro / 5-5`、`o1 / o1-mini / o1-preview / o1-pro`、`o3-mini / o3-mini-high`
- GPTs（`gpt-4-gizmo-g-*`）/ Team / Plus 账号 / 文件 / 图片 / 联网 / 画图
- AccessToken / RefreshToken / SessionToken（`rt_*` 新格式）多 Tokens 轮询 + 失败自动重试
- O3 / O1 系列推理过程输出
- conversation_id / parent_message_id 续接（用于 [LibreChat 集成](#librechat--new-api-集成)）

### 官网镜像（Gateway 模式）

`ENABLE_GATEWAY=true` 后启用：

- `/login` 登录页 + 后台账号池随机抽取（`Seed` 设置随机账号）
- `/?token=xxx` 直接登录（值为 RefreshToken / AccessToken / SeedToken）
- 不同 SeedToken 会话隔离
- 支持 GPTs 商店、DeepResearch、Canvas
- 多语言切换、敏感接口禁用

### 工程化能力（nanashiwang 分支）

完整能力清单见上文 [✨ nanashiwang 分支新特性](#-nanashiwang-分支新特性) 表格。

---

## API 使用

### 调用示例

```bash
curl --location 'http://127.0.0.1:5005/${API_PREFIX}/v1/chat/completions' \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer {{Token}}' \
  --data '{
    "model": "gpt-5-5",
    "messages": [{"role": "user", "content": "Say this is a test!"}],
    "stream": true
  }'
```

`{{Token}}` 可以是：

- 你账号的 `AccessToken` / `RefreshToken` —— 单账号直连
- 你设置的 `AUTHORIZATION` 环境变量值 —— 后台 Tokens 轮询（推荐）
- LibreChat → New-API 流转下来的 New-API key —— 见 [LibreChat 集成](#librechat--new-api-集成)

### Team 账号

传 `ChatGPT-Account-ID` header，或将其拼接在 Authorization：

```
Authorization: Bearer <Token>,<ChatGPT-Account-ID>
```

### 深度研究（Deep Research）

API 端兼容 ChatGPT 的深度研究功能，支持**两种触发方式**（任选其一）：

**方式 A：模型名后缀**（OpenAI 兼容客户端首选）

```bash
curl -N 'http://127.0.0.1:5005/${API_PREFIX}/v1/chat/completions' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {{Token}}' \
  -d '{
    "model": "o4-mini-deep-research",
    "stream": true,
    "messages": [{"role":"user","content":"2026 年量子计算的主要突破有哪些？请给出引用"}]
  }'
```

可用别名：`o3-deep-research` / `o4-mini-deep-research` / `gpt-4o-deep-research` / `deep-research`

**方式 B：`system_hints` 透传**（高级用法）

```bash
curl -N 'http://127.0.0.1:5005/${API_PREFIX}/v1/chat/completions' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {{Token}}' \
  -d '{
    "model": "gpt-5-5",
    "system_hints": ["research"],
    "stream": true,
    "messages": [{"role":"user","content":"对比主流 LLM 推理引擎的吞吐量与成本"}]
  }'
```

也可使用快捷开关 `"deep_research": true`。

**注意事项：**

- 账号需具备深度研究权限（Plus / Pro / Team），且本月额度未耗尽
- 单次任务耗时通常 5~15 分钟，反向代理需调高读取超时：`nginx proxy_read_timeout ≥ 1800s`、`cloudflare` 建议改用 WebSocket / 直连
- 流式响应包含：搜索查询提示 → 引用清单 → 中间思考 → 最终研究报告
- 不支持与 Gizmo（GPTs）同时使用，触发时会自动降级为 `primary_assistant` 模式

### Tokens 来源

- **AccessToken**：登录 chatgpt.com 后访问 [`https://chatgpt.com/api/auth/session`](https://chatgpt.com/api/auth/session) 取 `accessToken`
- **RefreshToken / SessionToken**：浏览器登录后 F12 抓 cookie，**强烈建议走 Harvester UI**（[`docs/COOKIE_HARVEST.md`](docs/COOKIE_HARVEST.md)）
- **免登录 GPT-3.5**：无需 Token

### Tokens 管理

1. 设置 `AUTHORIZATION` 环境变量作为授权码
2. 访问管理后台（`/{api_prefix}/admin/login`）→ Tokens 管理 / Harvester
3. 请求时把 `AUTHORIZATION` 当成 `APIKEY` 传入即可使用轮询

---

## 环境变量参考

> 表格仅列**最常用**变量；未列出的请勿设置或使用默认值。完整参考可在容器启动日志的 `Environment variables:` 区域查看。

| 分类 | 变量 | 默认值 | 说明 |
|---|---|---|---|
| 安全 | `API_PREFIX` | `None` | API 路径前缀（推荐设置，避免被扫描） |
| 安全 | `AUTHORIZATION` | `[]` | 授权码（多个用英文逗号分隔），用于 Tokens 轮询 |
| 安全 | `ADMIN_PASSWORD` | `None` | 管理后台登录密码 |
| 安全 | `ADMIN_IP_WHITELIST` | (空) | 管理后台 IP 白名单（CIDR 支持），强烈建议配置 |
| 请求 | `CHATGPT_BASE_URL` | `https://chatgpt.com` | 上游网关，多个用逗号分隔 |
| 请求 | `PROXY_URL` | `[]` | 全局代理 URL，多个用逗号分隔（也可 UI 配置） |
| 功能 | `HISTORY_DISABLED` | `true` | 不保存聊天记录到 ChatGPT 服务端 |
| 功能 | `ENABLE_LIMIT` | `true` | 不突破官方次数限制（防封号） |
| 功能 | `SCHEDULED_REFRESH` | `false` | 定时刷新 AccessToken |
| 功能 | `RANDOM_TOKEN` | `true` | 随机选取后台 Token（关闭则顺序轮询） |
| 网关 | `ENABLE_GATEWAY` | `false` | 启用官网镜像；开启后默认无认证，需配 `AUTH_KEY` 或 IP 白名单 |
| 网关 | `AUTO_SEED` | `true` | 启用随机账号模式（`seed` 参数自动匹配账号） |
| Antiban | `ENABLE_ANTIBAN` | `false`（multi 默认 `true`） | 风控规避层：IP 粘性桶 / 地域一致性 / 熔断自愈 |
| Antiban | `STRICT_IP_BINDING` | `true` | 无匹配代理时拒绝（不退化到母机直连） |
| Antiban | `BUCKET_MAX_ACCOUNTS_PER_IP` | `5`（multi 默认 `1`） | 每 IP 桶容纳的账号数 |
| Antiban | `CIRCUIT_429_COOLDOWN` | `1800` | 429 触发后账号冷却秒数 |
| Antiban | `CIRCUIT_403_COOLDOWN` | `3600` | 403/cf_chl_opt 触发后 IP 桶冷冻秒数 |
| Session | `ENABLE_SESSION_STICKY` | `false`（一键部署默认 `true`） | LibreChat 窗口级会话续接总开关 |
| Session | `SESSION_LC_FIELD` | `librechat_conversation_id` | LibreChat conversationId 在 request body 的字段名 |
| Session | `SESSION_TTL_DAYS` | `30` | 多少天未活跃自动清理映射 |
| Session | `SESSION_TRIM_TO_LAST_USER` | `true` | 命中映射时把 messages 截到最后一条 user |

详细文档：

- Antiban 工作原理：[`docs/FEATURES.md#1-antiban-风控规避层`](docs/FEATURES.md#1-antiban-风控规避层)
- 安全加固：[`docs/SECURITY.md`](docs/SECURITY.md)
- Cookie 采集：[`docs/COOKIE_HARVEST.md`](docs/COOKIE_HARVEST.md)
- 会话续接（本仓库新增）：[LibreChat 集成](#librechat--new-api-集成)

---

## 部署方式

### 一键部署（推荐）

零交互，默认安装多实例编排面板：

```bash
curl -fsSL https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/install.sh | bash
```

如需旧的单实例模式：

```bash
CHAT2API_MODE=single bash <(curl -fsSL https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/install.sh)
```

可选环境变量：

| 变量 | 用途 |
|---|---|
| `INSTALL_DIR` | 自定义安装目录（默认 `~/chat2api`） |
| `CHAT2API_PORT` | 监听端口（默认 `60403`） |
| `CHAT2API_MODE` | `multi`（默认）或 `single` |
| `INTERACTIVE=1` | 交互式询问密码 / API 前缀 |

### 直接源码部署

```bash
git clone https://github.com/nanashiwang/chat2api
cd chat2api
pip install -r requirements.txt
python app.py
```

### Docker

```bash
docker run -d --name chat2api \
  -p 5005:5005 \
  -v $(pwd)/data:/app/data \
  -e AUTHORIZATION=sk-your-key \
  ghcr.io/nanashiwang/chat2api:latest
```

### Docker Compose（自定义部署）

```bash
mkdir chat2api && cd chat2api
curl -fsSL https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/docker-compose.template.yml -o docker-compose.yml
# 创建 .env 写入 ADMIN_PASSWORD / AUTHORIZATION / API_PREFIX
docker compose up -d
```

### chat2api CLI 命令

部署完成后全局命令自动可用，单/多实例自动适配：

```bash
# 通用
chat2api status                  # 容器状态（多实例下含出口 IP 抽样）
chat2api update                  # 拉镜像并重建
chat2api logs [slug]             # 实时日志
chat2api restart / stop / start
chat2api uninstall               # 卸载：停止服务并删除安装目录
chat2api uninstall --keep-data   # 只停止服务，保留安装目录和数据
chat2api path                    # 打印安装目录

# 单实例专属
chat2api sync-template           # 检测并合并上游 docker-compose 模板的新 ENV
chat2api migrate prep            # 准备从单实例迁到多实例（仅备份+生成 csv）
chat2api migrate apply           # 切换到多实例（destructive，需输 yes 确认）
chat2api migrate rollback <dir>  # 从备份回滚到单实例

# 多实例专属
chat2api verify                  # 校验每实例的 admin / tokens 路由
chat2api secrets                 # 打印每实例 AUTH/ADMIN 凭据 + orchestrator 入口
chat2api shell <slug>            # 进入指定实例容器 shell
chat2api admin                   # 打印管理后台访问 URL
```

老机器升级最简方式：

```bash
# 拉新版 chat2api.sh 脚本
sudo curl -fsSL https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/chat2api.sh \
  -o /usr/local/bin/chat2api && sudo chmod +x /usr/local/bin/chat2api
chat2api update           # 拉镜像
chat2api sync-template    # 单实例：拉新 ENV
```

---

## 常见问题

### 错误码

| 状态码 | 原因 | 处理 |
|---|---|---|
| `401` | 当前 IP 不支持免登录 / 鉴权失败 | 换 IP / 配代理 / 检查 `AUTHORIZATION` |
| `403` | 风控触发（cf_chl_opt / 区域限制） | 看日志，配住宅代理；antiban 会自动冷却 IP 桶 |
| `429` | 1 小时内请求超限 | 等待或换 IP；antiban 会自动账号冷却 |
| `500` | 服务器内部错误 | 看 chat2api 日志 |
| `502` | 上游网关错误 | 换网络环境 / 检查代理 |

### 已知情况

- **日本 IP** 很多不支持免登录 GPT-3.5，建议美国 IP
- **GPT-4o 免费** 99% 账号支持，但按 IP 区域开启（日本/新加坡 IP 概率较高）
- **机房 IP**（DigitalOcean / WARP / Vultr 等）几乎已被风控；优先用住宅或移动蜂窝代理

### 提问前请准备

1. 启动日志截图（敏感信息打码，环境变量 + 版本号必备）
2. 报错日志（含 chat2api / nginx / 上游）
3. 接口返回的状态码和响应体

---

## 学习交流声明

> ⚠️ **本项目仅供学习与技术交流，请勿用于任何商业或违反 [OpenAI 服务条款](https://openai.com/policies/terms-of-use) 的用途。**

使用本项目即代表你已阅读并同意以下条款：

- 仅出于个人学习、技术研究、交流目的使用
- 不得用于任何形式的商业牟利
- 不得用于任何违反 OpenAI 服务条款或所在地法律法规的活动
- 一切因使用本项目产生的风险（账号被封、数据丢失、服务中断、法律责任等）由使用者**自行承担**
- 作者及贡献者不对使用本项目造成的任何直接或间接后果负责

如果你不接受上述任何一条，请立即停止使用并删除本项目。

本分支基于 [LanQian528/chat2api](https://github.com/LanQian528/chat2api) 二次开发，所有上游代码版权归原作者所有。

---

## License

MIT License
