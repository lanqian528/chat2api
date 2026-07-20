# chat2api 生产环境安全加固指南

> 把管理后台暴露在公网是个严肃的安全问题。本文档给出分层防护建议。

## 威胁模型

| 威胁 | 描述 | 缓解层 |
|---|---|---|
| **暴力破解密码** | 攻击者拿字典撞 `ADMIN_PASSWORD` | 应用层（已有 5 次失败锁 10 分钟） |
| **DDoS / CC** | 刷登录接口打满带宽 | CF 边缘过滤 |
| **未授权访问** | 扫 80/443 端口发现后台入口 | CF + IP 白名单 |
| **XSS / CSRF** | 通过前端漏洞偷 admin cookie | HttpOnly cookie（已有） |
| **MITM** | 明文 HTTP 传输密码被窃听 | CF 自动 HTTPS |
| **配置泄露** | docker-compose.yml 里的密码入 git | 用 .env 文件（已推荐） |

---

## 防护分层（按效果/成本排序）

### 🥇 第 0 层：Cloudflare 免费版（10 分钟，0 代码）

1. 把你服务器的域名（例如 `api.your-domain.com`）DNS 解析指向服务器 IP
2. 在 Cloudflare 把该域名 **接入**（免费套餐即可）
3. 开启 **橙色云朵 proxied** 图标
4. SSL/TLS → 设为 `Full (strict)`
5. 防火墙规则 → 根据需要开启：
   - **Country block**：只允许你的国家访问（可选）
   - **Challenge (I'm Under Attack)**：被攻击时一键启用
   - **Rate limiting**：对 `/admin/login` 10 次/分钟限流
6. 服务器侧
   - 防火墙只允许 Cloudflare IP 段连 443，其他全拒绝
   - CF 官方 IP 段：https://www.cloudflare.com/ips/

**效果**：
- 服务器真实 IP 隐藏
- HTTPS 自动（Let's Encrypt 类似）
- CC 防护
- WAF 基础规则
- 访问日志更详细

如果配了 CF，在 chat2api 设置：
```yaml
environment:
  ADMIN_TRUST_PROXY: 'true'   # 信任 X-Forwarded-For（IP 白名单会读真实客户端 IP）
```

---

### 🥈 第 1 层：IP 白名单（5 行配置）

只允许**你家宽带 IP + VPN 出口 IP**访问管理后台：

```yaml
environment:
  ADMIN_IP_WHITELIST: '1.2.3.4,5.6.7.0/24,2001:db8::/32'
  ADMIN_TRUST_PROXY: 'true'   # 如果走了 CF / Nginx 反代才开
```

格式：
- 单 IP：`1.2.3.4`
- CIDR 子网：`192.168.1.0/24`
- IPv6：`2001:db8::1` 或 `2001:db8::/32`
- 多条逗号分隔

**行为**：
- 白名单**内** IP：正常看到登录页
- 白名单**外** IP：所有 `/admin/*` 路径 **403**，连登录表单都看不到

**注意**：
- 如果你的 IP 是动态的（家用宽带），可用 DDNS + 脚本每小时更新 CIDR
- 调用 OpenAI API 的 `/v1/chat/completions` **不受白名单限制**（只保护后台）

---

### 🥉 第 2 层：应用层（已默认开启，无需配置）

| 功能 | 说明 |
|---|---|
| 登录失败锁定 | 同 IP 连续 5 次错误 → 10 分钟不能重试 |
| HttpOnly Cookie | 防 XSS 偷 admin token |
| SameSite=Strict | 防 CSRF |
| 速率限制 | 管理接口 120 次/分钟 |
| 密码隔离 | `ADMIN_PASSWORD` 必须独立，不再允许回退到 `AUTHORIZATION` |
| 分级错误响应 | 未配置 ADMIN_PASSWORD 时整个后台返回 503，而不是误放行 |

---

## Cloudflare 配置详细步骤

### 1. 域名接入 CF

1. 注册 cloudflare.com 免费账号
2. Add Site → 输入你的域名 → Free 套餐
3. CF 会给你两个 NS，到你的域名注册商把 NS 改成 CF 的
4. 等待生效（10 分钟到 24 小时）

### 2. DNS 记录

A 记录 `api.your-domain.com` → 你的服务器公网 IP
- **代理状态选 Proxied（橙色云）**

### 3. SSL/TLS 配置

- SSL/TLS → Overview → 设为 `Full (strict)`（推荐）
- Edge Certificates → Always Use HTTPS: ON
- Edge Certificates → Min TLS Version: TLS 1.2

### 4. 防火墙规则（WAF → Custom rules）

**规则 1：保护管理后台**
```
Expression: (http.request.uri.path contains "/admin") and (ip.src ne 1.2.3.4)
Action: Block
```

**规则 2：限流登录接口**
```
Expression: (http.request.uri.path eq "/your_prefix/admin/login") and (http.request.method eq "POST")
Action: Managed Challenge
Rate: 5 requests per 10 seconds
```

### 5. 服务器防火墙（UFW / iptables）

只允许 Cloudflare IP 段 + 你自己的运维 IP：

```bash
# Ubuntu UFW 示例
sudo ufw default deny incoming
sudo ufw allow 22/tcp    # SSH（建议改非默认端口）
# CF IPv4 段（复制自 https://www.cloudflare.com/ips-v4）
for ip in 173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 \
          103.31.4.0/22 141.101.64.0/18 108.162.192.0/18 \
          190.93.240.0/20 188.114.96.0/20 197.234.240.0/22 \
          198.41.128.0/17 162.158.0.0/15 104.16.0.0/13 \
          104.24.0.0/14 172.64.0.0/13 131.0.72.0/22; do
  sudo ufw allow from $ip to any port 60403
done
sudo ufw enable
```

这样服务器 60403 端口只接受 CF 转发的流量，攻击者扫描你真实 IP 无法直连。

---

## 验证

配完后测试：

```bash
# 1. 从白名单外 IP 访问
curl -I https://api.your-domain.com/nanapi-2026-a1/admin/login
# 预期: 403 Forbidden (IP 白名单拦截)

# 2. 从白名单 IP 访问
curl -I https://api.your-domain.com/nanapi-2026-a1/admin/login
# 预期: 200 HTML 登录页

# 3. 服务器日志应能看到真实客户端 IP（ADMIN_TRUST_PROXY=true 生效）
docker compose logs chat2api --tail 20 | grep admin-ipwl
# 预期: [admin-ipwl] 拒绝 IP: xxx.xxx.xxx.xxx （而不是 CF 的 IP）

# 4. 尝试直接用服务器 IP 访问（绕过 CF）
curl -I http://你的服务器IP:60403/
# 预期: 超时或拒绝连接（UFW 拦截）
```

---

## 额外建议

- **备份 data/ 目录**：每天一次，放 S3 或另一台机器
- **限制 SSH**：改端口 + 公钥登录 + Fail2ban
- **监控 /admin/logs**：出现大量 401 / 拒绝 IP 时立即警觉
- **定期轮换 ADMIN_PASSWORD**：每 3 个月换一次
- **审计 data/harvester_accounts.json**：发现不认识的 email 立即查
