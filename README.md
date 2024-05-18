# CHAT2API

🤖 一个简单的ChatGPT TO API代理

🌟 无需账号即可使用免费、无限的 `GPT-3.5`

💥 支持AccessToken使用账号，支持 `GPT-4`、`GPT-4o`、 `GPTs`

🔍 回复格式与真实api完全一致，适配几乎所有客户端

## 交流群

https://t.me/chat2api 要提问请先阅读完仓库介绍

## 功能

> 已完成
> - [x] 免登录 GPT3.5 对话
> - [x] GPT-3.5 对话 (传入模型名不包含gpt-4，则默认使用gpt-3.5，也就是text-davinci-002-render-sha)
> - [x] GPT-4 对话 (传入模型名包含: gpt-4，gpt-4o，gpt-4-moblie 即可使用对应模型， 需传入AccessToken)
> - [x] GPT-4 画图、代码、联网
> - [x] 支持GPTs (传入模型名：gpt-4-gizmo-g-*)
> - [x] 上传图片、文件 (格式为API对应格式，支持url和base64)
> - [x] 反向代理 UI (http://127.0.0.1:5005, 不支持登录使用)

> TODO
> - [ ] 暂无，欢迎提 issue

## 部署

### (推荐) zeabur部署

[![Deploy on Zeabur](https://zeabur.com/button.svg)](https://zeabur.com/templates/6HEGIZ?referralCode=LanQian528)

### 直接部署

```bash
git clone https://github.com/LanQian528/chat2api
cd chat2api
pip install -r requirements.txt
python app.py
```

### Docker部署

您需要安装Docker和Docker Compose。

```bash
docker run -d \
  --name chat2api \
  -p 5005:5005 \
  lanqian528/chat2api:latest
```

### (推荐，可用4.0) Docker Compose部署

创建一个新的目录，例如chat2api，并进入该目录：

```bash
mkdir chat2api
cd chat2api
```

在此目录中下载库中的docker-compose.yml文件：

```bash
wget https://raw.githubusercontent.com/LanQian528/chat2api/main/docker-compose.yml
```

修改docker-compose.yml文件中的环境变量，保存后：

```bash
docker-compose up -d
```

## 使用

- 在网页使用, 直接访问以下地址, 仅支持使用免登 GPT3.5:

```
http://127.0.0.1:5005
```

- 使用 API , 支持传入 AccessToken 或 RefreshToken, 可用 GPT-4, GPT-4o, GPTs:

```bash
curl --location 'http://127.0.0.1:5005/v1/chat/completions' \
--header 'Content-Type: application/json' \
--header 'Authorization: Bearer {{Token}}' \
--data '{
     "model": "gpt-3.5-turbo",
     "messages": [{"role": "user", "content": "Say this is a test!"}],
     "stream": true
   }'
```
> `Token` 处填写你账号的 `AccessToken` 或 `RefreshToken`
> - `AccessToken` 获取: chatgpt官网登录后，再打开 https://chatgpt.com/api/auth/session 获取 `accessToken` 这个值
> - 免登录 gpt3.5 无需传入 Token


## ArkoseToken

> #### 目前支持外部服务提供 ArkoseToken
>
> #### 推荐使用 docker-compose 方式部署, 已内置 Arkose 服务

1. 设置环境变量ARKOSE_TOKEN_URL

2. 在需要`ArkoseToken`的时候，`chat2api`会向`ARKOSE_TOKEN_URL`发送`POST`请求

3. 请按照以下格式提供外部服务：

- 请求体：

```request body
{"blob": "rFYaxQNEApDlx/Db.KyrE79pAAFBs70CYtbM4pMNUsc7jIkLGdiDs7vziHRGe78bqWXDo0AYyq2A10qIlcTt89lBYXJqCbONC/nD8C199pEZ/c9ocVKKtM27jZQ7fyOpWd9p5qjKeXT4xEGBFpoE3Re1DwdQeijYp7VMJQyw7RYN+IDB1QEx3aKSO6aTI+ivnhw9ztfn/p1SkvAyyOhur/ArF08WQ+rXQpxpttaSQlzMsIwlYbuUUuYE2f9JrQaYG7qip1DKvju111P6wTNy4QVlMXG32VrzaOWh4nmQ0lOcZ1DmN6u2aeJZotffHV2zOOQAqqnParidTbN+qFre2t77ZwBuGKGqLyT8LeOp02GdFwcyw0kkeX+L7vwYAzBpjA5ky0r0X+i8HpzWt8QCyWzEW9kHn9LLCTwg2MOumzjb66Ad4WDe+C1bAcOKuEyXiYh+a1cWZAOdzEuxEg90yCfI7DZR94BsoDR85gEC/Og88i098u5HV7hZZEOQ6J8fmi68FSyPkN7oLCmBsZCMAZqzapNP/MkeIMExrdw7Jf/PtMrZN4bwM56mWfyIJf5h/zXu8PUajVwE9Pj/M5VtB0spZg49JNeHExosVCAB0C0JW+T8vEIwoqiY4pRQ0lbMHTQZFpU2xURTgcgh+m6g1SEYR1FY3de1XnzfiTQq1RTNJPydj5xpt6r6okr8yIJdRhmVXlQI+pS7vi3+Lls2hnpr7L+l1mcUIMPZNBCs3AUFJNpp6SwQjZkPvKggg1p+uS6PdvKRizM9O9+FKc103AhuSia8KTrvU8tWhBhCzIHCD4LNfnkjuBWSdbDttva4AEXUoPuKkQCWaBzq4lQPUIHFOM9HmNe738vVkNdAuOYffxDNegcpIxLVgZGfbgLQ="}
```

- 响应体：

```response body
{"token": "45017c7bb17115f36.7290869304|r=ap-southeast-1|meta=3|metabgclr=transparent|metaiconclr=%23757575|guitextcolor=%23000000|pk=0A1D34FC-659D-4E23-B17B-694DCFCF6A6C|at=40|sup=1|rid=3|ag=101|cdn_url=https%3A%2F%2Ftcr9i.openai.com%2Fcdn%2Ffc|lurl=https%3A%2F%2Faudio-ap-southeast-1.arkoselabs.com|surl=https%3A%2F%2Ftcr9i.openai.com|smurl=https%3A%2F%2Ftcr9i.openai.com%2Fcdn%2Ffc%2Fassets%2Fstyle-manager"}
```



## 常见问题

> - 错误代码：
>   - `401`：当前IP不支持免登录，请尝试更换IP地址，或者在环境变量 `PROXY_URL` 中设置代理。
>   - `403`：请在日志中查看具体报错信息
>   - `429`：当前IP请求1小时内请求超过限制，请稍后再试，或更换ip。
>   - `500`：服务器内部错误，请求失败。
>   - `502`：服务器网关错误，或网络不可用，请尝试更换网络环境。

> - 已知情况：
>  - 日本IP很多不支持免登，免登3.5建议使用美国IP
>  - 99%的账号都支持免费 `GPT-4o` ，但根据IP地区开启，目前日本和新加坡IP已知开启概率较大

> - AccessToken 如何获取？
>  - chatgpt官网登录后，再打开 https://chatgpt.com/api/auth/session 获取 `accessToken` 这个值
> - PLUS账号报错`403`？
>  - PLUS账号需要配置 `ArkoseToken`，请根据上文进行配置
> - ArkoseToken 是什么，怎么获取？
>  - 请参考上文的说明，更多请参考 https://www.arkoselabs.com/



## 环境变量

每个环境变量都有默认值，如果不懂环境变量的含义，请不要设置，更不要传空值

```
API_PREFIX=your_prefix                               // API前缀，设置后需请求 /your_prefix/v1/chat/completions
CHATGPT_BASE_URL=https://chatgpt.com                 // ChatGPT网关地址，设置后会改变请求的网站，多个网关用逗号分隔
HISTORY_DISABLED=true                                // 是否不保存聊天记录并返回 conversation_id，true为不保存且不返回
PROXY_URL=your_first_proxy, your_second_proxy        // 代理url，多个代理用逗号分隔
ARKOSE_TOKEN_URL=https://arkose.example.com/token    // 获取Arkose token的地址，上文有提供说明
POW_DIFFICULTY=000032                                // 要解决的工作量证明难度，字符串越小，计算时间越长，建议000032
RETRY_TIMES=3                                        // 出错重试次数
ENABLE_GATEWAY=true                                  // 是否启用网关模式(WEBUI)，true为启用
```

## License

MIT License
