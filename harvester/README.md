# Chat2API Harvester

> ⚠️ **DEPRECATED（已废弃，保留供参考）**
>
> 本 Playwright CLI 工具已被 chat2api 管理后台内置的"**🌐 浏览器登录**"功能取代。
>
> 新方案优势：
> - 不用在本地装 Playwright / chromium（省 250MB）
> - 不用维护 `accounts.csv` 密码文件
> - 不用本地 venv / Python 环境
> - Arkose 挑战由真实浏览器处理，触发概率更低
> - 完全 UI 驱动，一个账号 2 次粘贴完成
>
> **迁移方法**：
> 1. 打开 `http://你的服务器:60403/{API_PREFIX}/admin/routing`
> 2. 左侧 → "账号采集 Harvester"
> 3. 点某账号行的 **[🌐 浏览器登录]** 按钮，按向导 2 次粘贴 URL 即可
>
> 本目录代码仅作为历史参考保留。**无需运行本目录任何命令**。
>
> 确认新方案无问题后可以直接 `rm -rf harvester/` 整个目录。

---

## （以下为原文档，仅供参考）

> 自家 ChatGPT 账号池 → RefreshToken 自动采集 → 写入 chat2api

本地 Python + Playwright 工具，用 iOS ChatGPT app 的 OAuth2 PKCE 流程，从自家账号登录并拿到 `rt_*` RefreshToken，自动通过管理后台 API 写入 chat2api 账号池。**一次人工辅助跑完，后续 2-3 个月由 chat2api 内建 `SCHEDULED_REFRESH` 接管刷新**。

---

## 适用场景

- 你有 20+ 个**自家** Team/Plus 账号（email + password）
- 希望彻底摆脱共享渠道 token 频繁失效
- 能接受"首次约 30 分钟人工辅助登录，之后全自动"的节奏

---

## 前置要求

- Python 3.9+（Mac 系统自带 `python3` 即可）
- chat2api 已在本机或局域网运行（管理后台可通）
- chat2api 的 `ADMIN_PASSWORD` 已配置
- 账号凭据：email + password（混合 2FA 可以）

---

## 安装

```bash
cd /Users/nanashiwang/Documents/Projects/chat2api/harvester

# 创建虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright chromium（首次约 250MB，只需一次）
playwright install chromium
```

---

## 配置

### 1. `.env`

```bash
cp .env.example .env
```

编辑 `.env`，至少填：

```ini
CHAT2API_BASE_URL=http://localhost:60403
CHAT2API_API_PREFIX=nanapi-2026-a1
CHAT2API_ADMIN_PASSWORD=与docker-compose里一致
```

其他参数（超时、并发、OAuth client_id）一般不需要动。

### 2. `accounts.csv`

```bash
cp accounts.csv.example accounts.csv
```

编辑 `accounts.csv`，字段：

| 列名 | 必填 | 说明 |
|---|---|---|
| `email` | ✓ | 登录邮箱 |
| `password` | ✓ | 登录密码（含特殊字符用双引号包裹） |
| `totp_secret` | | Google Authenticator 的 base32 secret，有 2FA 时填 |
| `note` | | 导入 chat2api 后的备注，如 "Team-01 HK" |
| `proxy_name` | | chat2api 里已存在的代理名，会自动绑定 |

示例：
```csv
email,password,totp_secret,note,proxy_name
alice@example.com,Pwd@12345,,Team-01 HK,HK-Resi-01
bob@example.com,"Pwd,with,comma",JBSWY3DPEHPK3PXP,Team-02 JP,JP-Resi-02
```

**⚠️ `.env` 和 `accounts.csv` 已在 `.gitignore` 中，不会被提交。**

---

## 运行

### 全量（跳过已成功）

```bash
python -m src.harvest
```

浏览器会弹出，脚本自动填邮箱+密码+TOTP。若遇到 **Arkose 人机验证**，你需要手工点一下（脚本等 90s）。

首次建议：

```bash
# 只跑一个测试账号
python -m src.harvest --only alice@example.com
```

跑通之后再全量。

### 按需运行

```bash
python -m src.harvest --only a@b.com,c@d.com   # 指定账号
python -m src.harvest --failed                  # 只重试上次失败
python -m src.harvest --force                   # 忽略 state，全量重跑
python -m src.harvest --export tokens.json      # 不调 chat2api，导出完整 rt 到 JSON
```

### 什么时候跑？

- **首次部署**：跑 1 次全量
- **rt 寿命到期**（约 60-90 天后 chat2api 日志会报大量 `refresh_token_expired`）：跑 1 次 `--failed`
- **新增账号**：把新账号追加到 `accounts.csv`，跑 `--only 新邮箱`

---

## 工作原理

```
1. PKCE 生成 code_verifier + code_challenge
2. Playwright 打开 https://auth0.openai.com/authorize?client_id=<iOS>
3. 自动填 email → password → TOTP（如果有）
4. Arkose 挑战时暂停 90s 等人工点击
5. 登录成功 → Auth0 重定向到 com.openai.chat:// 回调
6. 从 URL 抽取 authorization code
7. POST /oauth/token 用 code + verifier 换 refresh_token
8. 立即调用 chat2api /admin/routing/accounts/import 写入
```

- 每账号一个独立 Playwright profile（`profiles/<sha256>/`）。第二次登录同账号可能因为 cookie 保留而免过 Arkose。
- rt 完整值只在内存里短暂出现（oauth_flow.harvest_one），`on_success` 回调立即写入 chat2api 后即被释放。
- `state/<sha256>.json` 记录最近一次成功/失败时间，重启脚本会按 `--force` 选项决定是否跳过。

---

## 故障排查

| 症状 | 可能原因 | 处理 |
|---|---|---|
| `chat2api 鉴权失败` | `.env` 里 ADMIN_PASSWORD 错 | 对照 chat2api 的 `docker-compose.yml` |
| `chat2api 后台已禁用` | chat2api 未配 ADMIN_PASSWORD | 先修好 chat2api |
| `chat2api 不可达` | 端口/地址错 | 确认 `CHAT2API_BASE_URL` 能 curl 通 |
| 浏览器打开后长时间卡住 | Arkose 未过 / 页面改版 | headful 观察；若选择器失效联系维护 |
| 某账号一直密码错 | 真的错了 / 被锁定 | 检查是否需要解锁（登录网页一次） |
| Playwright 装不上 chromium | 网络问题 | 配 `HTTPS_PROXY` 后重跑 `playwright install` |

查日志：`logs/harvester.log`（密码和 rt 已自动脱敏）。

---

## 安全提醒

- `accounts.csv` 里是你账号的**原文密码**——请：
  - 不要放在会同步到云盘的目录
  - 不要 commit 到任何 git（`.gitignore` 已防护）
  - 跑完可选 `rm accounts.csv` 只保留 state
- Playwright profiles 含 cookie/session，`chmod 700 profiles/` 限制权限
- 日志文件做了 rt/JWT 截断，但别分享整个 `logs/` 给他人

---

## 目录结构

```
harvester/
├── .env                  # 你的配置（gitignored）
├── .env.example
├── accounts.csv          # 你的账号（gitignored）
├── accounts.csv.example
├── requirements.txt
├── README.md
├── src/
│   ├── harvest.py        # CLI 入口
│   ├── config.py         # .env + CSV 解析
│   ├── models.py         # Account / TokenSet / HarvestResult
│   ├── oauth_flow.py     # PKCE + Playwright + token 交换
│   ├── totp.py           # 2FA
│   ├── chat2api_client.py
│   ├── cache.py          # per-account state
│   └── log_setup.py
├── profiles/             # Playwright persistent contexts (runtime)
├── state/                # per-account 状态 JSON (runtime)
└── logs/                 # 执行日志 (runtime)
```

---

## License

MIT（与主项目一致）
