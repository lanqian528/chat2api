# CHAT2API

🌟 无需账号即可使用免费、无限的GPT3.5

💥 支持AccessToken使用账号，支持GPT4.0

🔍 以假乱真，回复格式与真实api完全一致，支持max_tokens，stream等参数，并且支持token数计算

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

## 使用GPT4

#### 目前支持外部服务提供ArkoseToken

1. 设置环境变量ARKOSE_TOKEN_URL

2. 在需要`ArkoseToken`的时候，`chat2api`会向`ARKOSE_TOKEN_URL`发送`POST`请求

3. 请按照以下格式提供外部服务：

- 请求体：
```request body
{
    blob: "rFYaxQNEApDlx/Db.KyrE79pAAFBs70CYtbM4pMNUsc7jIkLGdiDs7vziHRGe78bqWXDo0AYyq2A10qIlcTt89lBYXJqCbONC/nD8C199pEZ/c9ocVKKtM27jZQ7fyOpWd9p5qjKeXT4xEGBFpoE3Re1DwdQeijYp7VMJQyw7RYN+IDB1QEx3aKSO6aTI+ivnhw9ztfn/p1SkvAyyOhur/ArF08WQ+rXQpxpttaSQlzMsIwlYbuUUuYE2f9JrQaYG7qip1DKvju111P6wTNy4QVlMXG32VrzaOWh4nmQ0lOcZ1DmN6u2aeJZotffHV2zOOQAqqnParidTbN+qFre2t77ZwBuGKGqLyT8LeOp02GdFwcyw0kkeX+L7vwYAzBpjA5ky0r0X+i8HpzWt8QCyWzEW9kHn9LLCTwg2MOumzjb66Ad4WDe+C1bAcOKuEyXiYh+a1cWZAOdzEuxEg90yCfI7DZR94BsoDR85gEC/Og88i098u5HV7hZZEOQ6J8fmi68FSyPkN7oLCmBsZCMAZqzapNP/MkeIMExrdw7Jf/PtMrZN4bwM56mWfyIJf5h/zXu8PUajVwE9Pj/M5VtB0spZg49JNeHExosVCAB0C0JW+T8vEIwoqiY4pRQ0lbMHTQZFpU2xURTgcgh+m6g1SEYR1FY3de1XnzfiTQq1RTNJPydj5xpt6r6okr8yIJdRhmVXlQI+pS7vi3+Lls2hnpr7L+l1mcUIMPZNBCs3AUFJNpp6SwQjZkPvKggg1p+uS6PdvKRizM9O9+FKc103AhuSia8KTrvU8tWhBhCzIHCD4LNfnkjuBWSdbDttva4AEXUoPuKkQCWaBzq4lQPUIHFOM9HmNe738vVkNdAuOYffxDNegcpIxLVgZGfbgLQ="
}
```

- 响应体：
```response body
{
    "token": "45017c7bb17115f36.7290869304|r=ap-southeast-1|meta=3|metabgclr=transparent|metaiconclr=%23757575|guitextcolor=%23000000|pk=0A1D34FC-659D-4E23-B17B-694DCFCF6A6C|at=40|sup=1|rid=3|ag=101|cdn_url=https%3A%2F%2Ftcr9i.openai.com%2Fcdn%2Ffc|lurl=https%3A%2F%2Faudio-ap-southeast-1.arkoselabs.com|surl=https%3A%2F%2Ftcr9i.openai.com|smurl=https%3A%2F%2Ftcr9i.openai.com%2Fcdn%2Ffc%2Fassets%2Fstyle-manager"
}
```

## 高级设置

默认情况不需要设置，除非你有需求

### 环境变量

```
AUTHORIZATION=your_first_token, your_second_token     // 使用免登3.5的Bearer token，不设置则无需Bearer token
FREE35_BASE_URL=https://chat.openai.com/backend-anon  // 免登3.5的网关地址
CHATGPT_BASE_URL=https://chat.openai.com/backend-api  // 非免登3.5、4.0的网关地址
HISTORY_DISABLED=true                                 // 是否保存聊天记录
PROXY_URL=your_first_proxy, your_second_proxy         // 代理url，多个代理用逗号分隔
ARKOSE_TOKEN_URL=https://arkose.example.com/token     // 获取Arkose token的地址，上文有提供说明
RETRY_TIMES=3                                         // 重试次数
```

## License

MIT License
