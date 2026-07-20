# 新功能总览（nanashiwang 分支）

> 本文档汇总 nanashiwang 分支相比上游 `LanQian528/chat2api` 的增强功能。
> 按能力分类，每节包含：功能简介 → 配置方式 → 使用方式。

---

## 目录

1. [Antiban 风控规避层](#1-antiban-风控规避层)
2. [Harvester 账号采集](#2-harvester-账号采集)
3. [管理后台增强](#3-管理后台增强)
4. [系统日志 UI](#4-系统日志-ui)
5. [安全加固](#5-安全加固)
6. [新版 Token 支持](#6-新版-token-支持)
7. [一键部署](#7-一键部署)

---

## 1. Antiban 风控规避层

> 针对 OpenAI 对机房 IP / 批量登录 / 异常请求的风控，提供自动化保护。

### 功能

- **IP-账号粘性桶**：每个住宅 IP 绑定固定 N 个账号，账号**永不跨桶漂移**（OpenAI 对账号历史 IP 突变极敏感）
- **账号级冷却**：单账号两次请求间自动保持最小间隔（默认 60s）+ 抖动
- **IP 地域一致性**：根据代理 IP 自动调整 `Accept-Language` / `timezone` 等 header
- **熔断自愈**：403/cf_chl_opt 自动降级 IP 桶、429 自动账号退避（指数 60→300→1800s）
- **指纹持久化**：每账号独立 UA + screen + cores，永不漂移

### 配置（`.env` 或 docker-compose environment）

```yaml
ENABLE_ANTIBAN: 'true'                   # 总开关
STRICT_IP_BINDING: 'true'                # 严格 IP 绑定（有代理池时开）
BUCKET_MAX_ACCOUNTS_PER_IP: '5'          # 每个 IP 容纳的账号数
ACCOUNT_MIN_INTERVAL_SECONDS: '60'       # Team/Plus 最小间隔
FREE_ACCOUNT_MIN_INTERVAL_SECONDS: '180' # 免费账号最小间隔
ACCOUNT_COOLDOWN_JITTER: '0.3'           # 冷却抖动 ±30%
ACCOUNT_MAX_WAIT_SECONDS: '30'           # 账号排队最长等待
IP_GEO_PROVIDER: 'ip-api'                # 地域查询提供商
CIRCUIT_429_COOLDOWN: '1800'             # 429 初始退避
CIRCUIT_403_COOLDOWN: '3600'             # 403 IP 桶冷冻时长
CIRCUIT_BUCKET_HEAL_MINUTES: '30'        # 桶自愈扫描间隔
```

### 观察

启动日志会看到：
```
[antiban] enabled | buckets=N accounts=M healthy=N degraded=0
```

运行中：管理后台 → "代理与路由" 可看到每个桶的状态（healthy/degraded/dead）。

---

## 2. Harvester 账号采集

> 从浏览器 cookie 采集 ChatGPT 网页会话，一次导入后 chat2api 自动续期数月。

### 核心能力

| 能力 | 实现 |
|---|---|
| 可视化 email 清单 | 管理后台 → "账号采集 Harvester" 页面 |
| 一键粘贴 Cookie | 🍪 按钮 + 多种粘贴格式自动识别（整段 document.cookie / 裸 value / 分片 .0 .1 .2） |
| 全角分号归一化 | 用户粘贴里意外的 `；`（中文）自动转 `;`（英文） |
| 每账号状态看板 | fresh / stale / failed / pending 颜色标识 |
| 代理绑定 | CSV 里的 proxy_name 自动反查并绑定代理 |
| 批量导入 | 支持上传 CSV（email,note,proxy_name 三列）|
| 自动上报 | cookie 验证成功自动更新看板 last_rt_prefix |

### 使用流程

详见 [`docs/COOKIE_HARVEST.md`](./COOKIE_HARVEST.md)。

1. 浏览器（走代理）登录 `https://chatgpt.com`
2. F12 Console:
   ```javascript
   document.cookie.split(';').filter(x=>x.includes('session-token')).join('; ')
   ```
3. 管理后台 → Harvester → 新增 email → 🍪 粘贴 Cookie → 完成

### 存储

- 元数据 `data/harvester_accounts.json`：email / note / proxy_name / last_rt_prefix
- **不存密码**，cookie 本身即凭证
- 权限：建议挂载 `./data` 为 600，单机部署

---

## 3. 管理后台增强

### 分页式布局

之前的滚动锚点式 nav 改为真正页面切换：

- 控制台总览
- 账号与令牌
- 代理与路由
- 账号采集 Harvester（新）
- 运行日志（新）

### 导入账号：支持文件上传 + 自动解析

- `.txt` 纯文本（每行 token，`#` 注释）
- `.json` 配置导出（递归扫描，识别 `refresh_token` / `access_token` 字段）
- 预览识别结果（SessionToken / RefreshToken / AccessToken 分桶）
- 复选后才写入（避免误操作）
- 2 MB 文件大小限制 + 后缀白名单

### 代理热加载

- UI "代理与路由" → 添加 / 编辑 / 删除 → **立即生效，无需重启**
- 保存后 antiban 桶自动重建（dead/orphaned 桶清理 + 未分配账号重分）
- 允许清空代理池（切到直连模式）

---

## 4. 系统日志 UI

> 把 `docker logs` 搬到 UI，方便远程运维。

### 功能

- **实时**：默认 3s 轮询增量（基于 `since_id`）
- **级别筛选**：ALL / DEBUG+ / INFO+ / WARNING+ / ERROR+
- **关键字搜索**：400ms 防抖
- **一键下载**：当前筛选结果 或 全部缓冲区
- **自动滚底** / **自动刷新** 开关
- **ANSI 颜色自动剥离**（日志里的 `\x1b[...]` 不会污染 UI）

### 配置

```yaml
LOG_BUFFER_SIZE: '3000'   # 内存环形缓冲条数，默认 2000
```

### 使用

管理后台 → "运行日志"

- `Ctrl+F` 前端查找支持
- 想定位某次 chat_refresh 失败 → 关键字输入 `chat_refresh` 即可

---

## 5. 安全加固

详见 [`docs/SECURITY.md`](./SECURITY.md)。

### 已修复的历史漏洞

| # | 漏洞 | 修复 |
|---|---|---|
| P0 | ADMIN_PASSWORD 未配时回退到 AUTHORIZATION 或空放行 | 未配置 → 整个后台返回 503 |
| P1 | `gateway/gpts.py` 未登录访问触发 `len(None)` 崩溃 | 加判空，重定向登录页 |
| P2 | admin_token 被服务端注入前端 JS 绕开 HttpOnly | 移除注入，HttpOnly + SameSite=Strict + Secure |

### 新增防护

| 防护 | 配置 | 效果 |
|---|---|---|
| 管理后台 IP 白名单 | `ADMIN_IP_WHITELIST=1.2.3.4,10.0.0.0/8` | 非白名单 IP 访问 `/admin/*` 直接 403 |
| 反代 IP 识别 | `ADMIN_TRUST_PROXY=true` | 走 CF/Nginx 后读真实 X-Forwarded-For |
| HttpOnly + SameSite=Strict | 默认 | 防 XSS 偷 admin cookie |
| 登录失败锁定 | 默认 | 同 IP 5 次错误锁 10 分钟 |
| 分级速率限制 | 默认 | 管理接口 120/min，登录接口 10/5min |

### 推荐链路

```
[公网用户]
    ↓
[Cloudflare 免费 WAF + 自动 HTTPS]
    ↓
[云服务器 UFW 只允许 CF IP 段 + 你的运维 IP]
    ↓
[chat2api IP 白名单 (ADMIN_IP_WHITELIST)]
    ↓
[ADMIN_PASSWORD 鉴权 + HttpOnly Cookie]
    ↓
[业务]
```

---

## 6. 新版 Token 支持

### 识别规则

`utils/routing.py::detect_token_type`：

| 前缀/长度 | 类型 | 刷新机制 |
|---|---|---|
| `sess-*` | **SessionToken**（新）| 调 `chatgpt.com/api/auth/session`，8 分钟缓存 |
| `rt_*`（长度 ≥ 60）| RefreshToken（Auth0 新格式）| 调 `auth.openai.com/oauth/token` |
| 长度正好 45 | RefreshToken（老格式） | 调 `auth.openai.com/oauth/token` |
| `eyJhbGciOi*` | AccessToken (JWT) | 不刷新（2 小时后过期） |
| `fk-*` | AccessToken (fakeopen) | 不刷新 |
| 其他 | CustomToken | 直接透传 |

### chat_refresh 现代化

- 端点从废弃的 `auth0.openai.com` 切到 **`auth.openai.com`**
- Content-Type 从 `application/json` → `application/x-www-form-urlencoded`
- User-Agent 从 iOS app → `Codex_CLI/0.1.0`
- 可通过环境变量完全覆盖：
  ```yaml
  OPENAI_AUTH_CLIENT_ID: 'app_EMoamEEZ73f0CkXaXp7hrann'
  OPENAI_AUTH_TOKEN_URL: 'https://auth.openai.com/oauth/token'
  OPENAI_AUTH_REDIRECT_URI: 'http://localhost:1455/auth/callback'
  OPENAI_AUTH_SCOPE: 'openid profile email offline_access'
  ```

### SessionToken 续期

每 8 分钟自动续一次 access_token。cookie 本身可用数月。流程：

```
请求进来 → verify_token 看 token 前缀
          ├── sess-  → sess2ac() 查缓存 → 命中返回 / 失效重新调 /api/auth/session
          ├── rt_    → rt2ac() 同上逻辑，调 auth.openai.com
          └── eyJ    → 直接用
```

---

## 7. 一键部署

> 在新云服务器上一行命令完成部署。

### 使用

```bash
# 方式 1：远程一行启动
curl -fsSL https://raw.githubusercontent.com/nanashiwang/chat2api/main/deploy/install.sh | bash

# 方式 2：clone 后本地跑
git clone https://github.com/nanashiwang/chat2api.git
cd chat2api/deploy
bash install.sh

# 交互模式（让脚本问你密码/前缀）
INTERACTIVE=1 bash install.sh

# 自定义安装目录
INSTALL_DIR=/opt/chat2api bash install.sh
```

### 脚本做的事

1. 检测 OS（Ubuntu / Debian / CentOS / RHEL / Rocky / Alma）和架构（amd64 / arm64）
2. 自动装 Docker + docker-compose 插件（如缺）
3. 下载 `docker-compose.template.yml` 到安装目录
4. 生成强随机凭据：
   - `ADMIN_PASSWORD`：24 位字母数字
   - `AUTHORIZATION`：`sk-` + 32 位
   - `API_PREFIX`：`api-` + 12 位
5. 写入 `.env`（chmod 600）
6. `docker compose up -d`
7. 自动安装宿主管理命令 `chat2api`
8. 等待健康检查通过
9. 打印访问 URL + 凭据 + 下一步操作指引

### 凭据安全

- `.env` 永远不进镜像（通过 `env_file` 挂载）
- 部署完自动 `chmod 600`
- 终端打印一次后就只能从 `.env` 看

### 升级

```bash
chat2api update
```

旧机器没有该命令时，重新跑一键部署脚本会沿用现有配置并补装。

---

## 配置速查表

| 变量 | 默认 | 作用 |
|---|---|---|
| `ADMIN_PASSWORD` | (必填) | 管理后台登录密码 |
| `AUTHORIZATION` | (必填) | API 调用方 Bearer token |
| `API_PREFIX` | (必填) | URL 路径前缀，建议随机 |
| `ADMIN_IP_WHITELIST` | 空 | 管理后台 IP 白名单（逗号 / CIDR） |
| `ADMIN_TRUST_PROXY` | false | 走 CF/Nginx 时设 true 读 XFF |
| `ENABLE_ANTIBAN` | false | Antiban 风控层总开关 |
| `STRICT_IP_BINDING` | true | 账号严格绑定 IP |
| `SCHEDULED_REFRESH` | false | 每 4 天定时刷新 RT |
| `LOG_BUFFER_SIZE` | 2000 | 日志面板内存条数 |
| `OPENAI_AUTH_CLIENT_ID` | Codex CLI | OAuth client_id 覆盖 |
| `OPENAI_AUTH_TOKEN_URL` | auth.openai.com | token 端点覆盖 |

---

## 常见问题速索引

| 问题 | 文档位置 |
|---|---|
| Cookie 怎么抓？ | [COOKIE_HARVEST.md](./COOKIE_HARVEST.md) |
| 公网部署安全？ | [SECURITY.md](./SECURITY.md) |
| chat_refresh 报 404 | 已修复，使用 `auth.openai.com` |
| 粘贴 cookie 报 latin-1 编码错 | 全角分号自动归一化，详见 COOKIE_HARVEST.md |
| 要不要用 Playwright 方案 | 已废弃，harvester/ 目录保留供参考 |
| 账号池怎么绑代理 | UI "代理与路由" → 编辑账号 → 选代理名 |
