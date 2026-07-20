# Cookie 抓取完整指南

> 本文教你从 ChatGPT 网页版抓取 **session-token cookie**，喂给 chat2api 使用。
> 这是目前**唯一可持续**的获取 ChatGPT 网页 API 访问凭证的方式（auth0 OAuth 已废弃）。

---

## 核心原理

### 你抓的是什么？

chatgpt.com 用 **NextAuth** 管理登录会话，用户登录后浏览器里会有一个加密 cookie：

```
__Secure-next-auth.session-token.0 = <JWE 片段 1>
__Secure-next-auth.session-token.1 = <JWE 片段 2>
[可能还有 .2 .3 ...]
```

为什么会分成 `.0 .1`？因为单个浏览器 cookie 上限约 4KB，而 NextAuth 的加密 session token 长度超过这个限制，就被**自动切片**存成多个 cookie。

chat2api 拿到 cookie 后，用它访问 `https://chatgpt.com/api/auth/session`，返回 JSON 中的 `accessToken`（JWT）就是调用 `/backend-api/conversation` 等接口的 Bearer token。

### 寿命对比

| 凭据 | 寿命 | 用途 |
|---|---|---|
| **session-token cookie** | **数月**（只要你不登出） | 长期凭证 → 存进 chat2api |
| accessToken (JWT) | **10-15 分钟** | 短命，chat2api 用 cookie 每次自动刷新 |

**所以必须抓 cookie，不能只抓 accessToken**。

---

## 🎯 设备无关，IP 地区强相关

Cookie 本身不绑设备——JWE 里没有"浏览器指纹"。但 **OpenAI 对 IP 行为有监控**：

```
❌ 危险：
   Windows 国内 IP 登录 → 拿 cookie → 贴到海外 VPS → chat2api 从美国 IP 调
   → OpenAI 看到"10 秒前在中国，现在在美国"→ 🚨 异地登录邮件 / 临时冻结

✅ 安全：
   登录拿 cookie 的 IP  ≈ chat2api 运行的 IP（同国或同大洲）
```

---

## 🟢 方法 A：SSH 动态端口转发（推荐 ⭐⭐⭐⭐⭐）

让你 Windows/Mac 浏览器**临时走云服务器出口**访问 chatgpt，使用 IP 和登录 IP 完全一致，零风险。

### 步骤

#### 1. 建立 SSH 隧道

**Windows**（需要 Git Bash / WSL / OpenSSH）：
```bash
ssh -D 1080 -N -q root@你的云服务器IP
# 保持这个窗口开着，别关
```

**Mac / Linux** Terminal 一样：
```bash
ssh -D 1080 -N -q root@你的云服务器IP
```

**PuTTY 用户**：
- Connection → SSH → Tunnels
- Source port: `1080`
- 勾选 `Dynamic`
- Add → 保存连接后开启

#### 2. 浏览器挂代理

**Chrome / Edge**：
1. 装扩展 [SwitchyOmega](https://chrome.google.com/webstore/detail/proxy-switchyomega)
2. 新建 profile：
   - Protocol: `SOCKS5`
   - Server: `127.0.0.1`
   - Port: `1080`
3. 启用该 profile

**Firefox**：
- 设置 → 网络设置 → 手动代理 → SOCKS 主机 `127.0.0.1:1080` → SOCKS v5

#### 3. 验证出口 IP

新标签页访问 `https://ifconfig.me`，显示的应该是**你云服务器的 IP**。

#### 4. 登录 chatgpt.com 抓 cookie

1. 访问 `https://chatgpt.com`
2. 登录（这次 OpenAI 看到的登录 IP = 云服务器 IP）
3. F12 → Console，输入：
   ```javascript
   document.cookie.split(';').filter(x=>x.includes('session-token')).join('; ')
   ```
4. 回车 → 右键复制输出
5. 关掉 SSH 隧道或关 SwitchyOmega

#### 5. 粘贴到 chat2api

- 管理后台 → "账号采集 Harvester" → 新增账号 → 🍪 粘贴 Cookie
- 粘贴 → [验证并导入] → 成功

---

## 🟡 方法 B：Clash 挂海外节点

如果不方便 SSH，但 Clash 有和云服务器**同地区**的节点：

1. Clash 切到云服务器同地区节点（日本 / 美国 / 新加坡）
2. 确认系统代理生效（访问 ifconfig.me 看 IP 地区对）
3. 按方法 A 的第 4-5 步抓 cookie

**不如方法 A 精确**（仍是两个不同 IP，只是地区一致），但触发风控的概率大幅降低。

---

## 🔴 方法 C：直接在本地抓（国内 IP → 海外 VPS）

- 第一次一定收到 OpenAI 异地登录警告邮件
- 点"是我本人" → 后续可用
- 不推荐但**可行**
- 适用场景：一次性测试账号，不介意邮件验证

---

## 正确粘贴格式

所有姿势都支持，后端自动识别：

### 姿势 1：F12 Console 一行抓（最推荐）

```javascript
document.cookie.split(';').filter(x=>x.includes('session-token')).join('; ')
```

输出：
```
 __Secure-next-auth.session-token.0=<v0>; __Secure-next-auth.session-token.1=<v1>
```

直接粘贴到 UI。

### 姿势 2：Application → Cookies 手工拼 Name=Value

```
__Secure-next-auth.session-token.0=<v0>;__Secure-next-auth.session-token.1=<v1>
```

### 姿势 3：只粘 Value（英文分号分隔）

如果只复制 Value 列（没 name）：

```
<v0>;<v1>
```

### 姿势 4：整段 document.cookie（含其他 cookie）

直接 Console 输入 `document.cookie` 复制整串，后端自动过滤噪音 cookie。

---

## ⚠️ 常见错误

| 错误信息 | 原因 | 解决 |
|---|---|---|
| `'latin-1' codec can't encode character '\uff1b'` | 粘贴里含**中文全角分号 `；`** | 系统会自动归一化；如仍报错，用 [替换工具](https://www.baidu.com/s?wd=全角半角转换) 转半角 |
| `未识别到有效的 session-token cookie` | 只粘了值但长度不够 / 格式错乱 | 用姿势 1 重新抓 |
| `500: Failed to connect to 127.0.0.1 port 7890` | 云服务器想走 Clash 但代理在你 Mac | 清空 `PROXY_URL` 或在 UI "代理与路由" 配**可达的**代理 |
| `session cookie 无效或过期` | Cookie 真过期了，或少抓了 `.1` | F12 看看是不是有 `.1`，全部抓 |
| `401 / cf_chl_opt` | IP 触发 CF 挑战 | 换代理、换 VPS 地区、或等 15 分钟再试 |

---

## 验证抓取成功

在 chat2api 后台点 "🍪 粘贴 Cookie" → 验证导入后，应看到：

```
✅ 成功导入 yours@example.com
access_token 预览: eyJhbGciOi...xxx
```

去"账号与令牌"页，新账号的"类型"列应显示 **SessionToken**。

测试真正能用：
```bash
curl -H "Authorization: Bearer $AUTHORIZATION" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4o","messages":[{"role":"user","content":"say hi"}]}' \
     http://your.server/your_prefix/v1/chat/completions
```

---

## Cookie 过期了怎么办

**Cookie 通常能用数月**。当你发现聊天失败时：

1. 管理后台 → "系统日志" 看到 `[sess2ac] status=401`
2. 说明 cookie 失效，需要重抓
3. 回到你 Windows 浏览器重复上面流程抓新 cookie
4. 管理后台 → 账号采集 → 对应邮箱点"编辑"或"🍪 粘贴 Cookie"（粘新的即可覆盖）

chat2api 的 `SCHEDULED_REFRESH` 只能刷新 **access_token**（短 JWT），**不能**帮你刷新 cookie 本身——cookie 过期必须人工重抓。

---

## 账号生命周期管理

推荐节奏：

```
 首次导入
    ↓
 [持续数月] ────→ 自动续 access_token（每 8 分钟，chat2api 自己做）
    ↓
 Cookie 过期 / 被强制登出
    ↓
 管理后台发现异常 → 重抓 cookie → 更新
```

如果你有 **多个账号池**（比如 20+），建议：
- 每月固定时间检查一次系统日志
- 用 `docker compose logs chat2api | grep -E "401|sess2ac.*fail"` 批量看哪些失效
- 一批一起重抓（SSH 隧道下同时开多个浏览器 Profile 登录）
