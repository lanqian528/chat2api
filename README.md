# CHAT2API

🌟无需账号即可使用免费、无限的gpt3.5，目前只能转gpt3.5的api

🔍以假乱真，回复格式与真实api完全一致，支持max_tokens，stream等参数，并且支持token数计算

## Deploy

### 直接部署

```bash
git clone https://github.com/LanQian528/chat2api
cd chat2api
pip install -r requirements.txt
python chat2api.py
```

### Docker部署

您需要安装Docker和Docker Compose。

```bash
docker run -d \
  --name chat2api \
  -p 5005:5005 \
  lanqian528/chat2api:latest
```

### Docker Compose部署

创建一个新的目录，例如chat2api，并进入该目录：

```bash
mkdir chat2api
cd chat2api
```

在此目录中下载库中的docker-compose.yml文件：

```bash
docker-compose up -d
```

## Usage

```bash
curl --location 'http://127.0.0.1:5005/v1/chat/completions' \
--header 'Content-Type: application/json' \
--data '{
     "model": "gpt-3.5-turbo",
     "messages": [{"role": "user", "content": "Say this is a test!"}],
     "stream": true
   }'
```

## 常见问题

- 错误代码：
  - `401`：当前IP不支持免登录，请尝试更换IP地址，或者在环境变量 `PROXY_URL` 中设置代理。
  - `403`：当前IP地址被 CF 盾拦截，请尝试更换IP地址，或者在环境变量 `PROXY_URL` 中设置代理。
  - `429`：当前IP请求1小时内请求超过限制，请稍后再试，或更换ip。
  - `500`：服务器内部错误，请求失败。
  - `502`：服务器网关错误，或网络不可用，请尝试更换网络环境。
- 来自`Xiaofei`的礼物：将环境变量设置为 `FREE35_BASE_URL=https://auroraxf.glitch.me/api` 或 `FREE35_BASE_URL=https://api.angelxf.cf/api` ，可无视CF盾和IP问题。

## 高级设置

默认情况不需要设置，除非你有需求

### 环境变量

```
AUTHORIZATION=your_first_token, your_second_token
FREE35_BASE_URL=https://chat.openai.com/backend-anon, https://auroraxf.glitch.me/api, https://api.angelxf.cf/api
HISTORY_DISABLED=false
PROXY_URL=your_first_proxy, your_second_proxy
RETRY_TIMES=3
```

[//]: # (## 鸣谢)

[//]: # ()

[//]: # (感谢各位大佬的pr支持，感谢。)

## License

MIT License
