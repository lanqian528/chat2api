# CHAT2API

🤖 A Simple ChatGPT TO API Proxy

🌟 Free and Unlimited `GPT-3.5` Without Account

💥 Supports AccessToken for Account Usage, Supports `O3-mini/high`, `O1/mini/Pro`, `GPT-4/4o/mini`, `GPTs`

🔍 Response Format Completely Consistent with Real API, Compatible with Almost All Clients

👮 Companion User Management Platform [Chat-Share](https://github.com/h88782481/Chat-Share) Requires Environment Variables to be Configured in Advance (Set ENABLE_GATEWAY to True, AUTO_SEED to False)

## Community Group

[https://t.me/chat2api](https://t.me/chat2api)

Before Asking Questions, Please Read the Repository Documentation Thoroughly, Especially the FAQ Section.

When Asking Questions, Please Provide:

1. Startup Log Screenshot (Sensitive Information Masked, Including Environment Variables and Version Number)
2. Error Log Information (Sensitive Information Masked)
3. Status Code and Response Body of the Interface Return

## Features

### Latest Version Number Stored in `version.txt`

### Reverse API Features
> - [x] Streaming and Non-streaming Transmission
> - [x] Login-free GPT-3.5 Conversation
> - [x] GPT-3.5 Model Conversation (Default to GPT-3.5 if model name does not contain gpt-4, i.e., text-davinci-002-render-sha)
> - [x] GPT-4 Series Model Conversation (Use corresponding model by including: gpt-4, gpt-4o, gpt-4o-mini, gpt-4-moblie, requires AccessToken)
> - [x] O1/O3/O4 series model dialogue (the corresponding model can be used by passing in model names including o3, o4-mini, etc., and AccessToken needs to be passed in)
> - [x] GPT-4 Model Drawing, Code, Internet Access
> - [x] Support GPTs (input model name: gpt-4-gizmo-g-*, the previous model can be changed, Team workspace projects need to use this)
> - [x] Support for Team Plus Accounts (Requires team account id)
> - [x] Upload Images and Files (API-compatible format, supports URL and base64)
> - [x] Can be Used as a Gateway, Supports Multi-machine Distributed Deployment
> - [x] Multi-account Polling, Supporting Both `AccessToken` and `RefreshToken`
> - [x] Request Failure Retry, Automatic Token Polling
> - [x] Tokens Management, Support Upload and Clearing
> - [x] Periodic Refresh of `AccessToken` using `RefreshToken` / Full Non-forced Refresh on Startup, Forced Refresh at 3 AM Every 4 Days
> - [x] Support File Download, Requires History Record Enabled
> - [x] Supports Model Inference Process Output for `O3-mini/high`, `O1/mini/Pro`

### Official Website Mirror Features
> - [x] Support for Official Native Mirror
> - [x] Backend Account Pool Random Selection, `Seed` Setting for Random Accounts
> - [x] Direct Login with `RefreshToken` or `AccessToken`
> - [x] Supports `O3-mini/high`, `O1/mini/Pro`, `GPT-4/4o/mini`
> - [x] Sensitive Information Interface Disabled, Partial Setting Interfaces Disabled
> - [x] /login Page, Automatic Redirect to Login Page After Logout
> - [x] /?token=xxx Direct Login, xxx is `RefreshToken` or `AccessToken` or `SeedToken` (Random Seed)
> - [x] Supports Session Isolation with Different SeedTokens
> - [x] Supports `GPTs` Store
> - [x] Supports Official-exclusive Features like `DeepReaserch`, `Canvas`
> - [x] Supports Language Switching

> TODO
> - [ ] None, Welcome to Submit `Issues`

## Reverse API

A fully `OpenAI`-compatible API that supports passing `AccessToken` or `RefreshToken`, usable with GPT-4, GPT-4o, GPT-4o-Mini, GPTs, O1-Pro, O1, O1-Mini, O3-Mini, O3-Mini-High:

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

Pass your account's `AccessToken` or `RefreshToken` as `{{ Token }}`.
You can also fill in the value of the environment variable `Authorization`, which will randomly select a backend account.

If you have a team account, you can pass in `ChatGPT-Account-ID` to use the Team workspace:

- Method One:
  Pass the `ChatGPT-Account-ID` value in the `headers`
- Method Two:
  `Authorization: Bearer <AccessToken or RefreshToken>,<ChatGPT-Account-ID>`

If the `AUTHORIZATION` environment variable is set, you can use the set value as `{{ Token }}` for multi-Token polling.

> - `AccessToken` retrieval: Log in to the ChatGPT website, then open [https://chatgpt.com/api/auth/session](https://chatgpt.com/api/auth/session) to get the `accessToken` value.
> - `RefreshToken` retrieval: Method not provided here.
> - Get `ChatGPT-Account-ID`:
> - Method ①, visit <https://chatgpt.com/admin> and use F12 to find the request <https://chatgpt.com/backend-api/accounts/UUID/users>, this ID is it.
> - Method ②, read the `account_user_id` in the response from the previous step, the UUID behind it.
> - Method ③, visit <https://chatgpt.com/api/auth/session> and find the id under account (not organizationId), or when the web page initiates a workspace conversation request, the F12 request header has this.
> - Get `gizmo` ID:
> - Method ①, open the project package, the URL starts with g-p, and remove the English version of the project name behind it.
> - Method ②, have a conversation in the workspace project, and find `gizmo_id` in the request body.
> - No login required for gpt-3.5, no token needed.

## Tokens Management

1. Configure the environment variable `AUTHORIZATION` as an `authorization code`, then run the program.
2. Access `/tokens` or `/{api_prefix}/tokens` to view the current number of Tokens, upload new Tokens, or clear Tokens.
3. Pass the `authorization code` configured in `AUTHORIZATION` to use polling Tokens for conversation

![tokens.png](docs/tokens.png)

## Official Website Native Mirror

1. Set the environment variable `ENABLE_GATEWAY` to `true`, then run the program. Note that enabling this allows others to directly access your gateway via domain.
2. Upload `RefreshToken` or `AccessToken` on the Tokens management page
3. Access `/login` to reach the login page

![login.png](docs/login.png)

4. Use on the official native mirror page

![chatgpt.png](docs/chatgpt.png)

## Environment Variables

Each environment variable has a default value. If you don't understand the meaning of an environment variable, do not set it, and definitely do not pass an empty value. Strings do not require quotes.

| Category | Variable Name | Example Value | Default Value | Description |
| -------- | ------------- | ------------- | ------------- | ----------- |
| Security | API_PREFIX | `your_prefix` | `None` | API prefix password. Without setting, it's easily accessible. After setting, request `/your_prefix/v1/chat/completions` |
| | AUTHORIZATION | `your_first_authorization`,`your_second_authorization` | `[]` | Authorization codes you set for using multiple accounts in token rotation, separated by English commas |
| | AUTH_KEY | `your_auth_key` | `None` | Set this for private gateway requiring `auth_key` request header |
| Request | CHATGPT_BASE_URL | `https://chatgpt.com` | `https://chatgpt.com` | ChatGPT gateway address. Setting this will change the requested website. Multiple gateways can be separated by commas |
| | PROXY_URL | `http://ip:port`,`http://username:password@ip:port` | `[]` | Global proxy URL, enabled when encountering 403, multiple proxies separated by commas |
| | EXPORT_PROXY_URL | `http://ip:port` or `http://username:password@ip:port` | `None` | Export proxy URL to prevent source site IP leakage when requesting images and files |
| Functionality | HISTORY_DISABLED | `true` | `true` | Whether to not save chat history and return conversation_id |
| | POW_DIFFICULTY | `00003a` | `00003a` | Proof of Work difficulty to solve, do not set if unsure |
| | RETRY_TIMES | `3` | `3` | Number of error retries. Using `AUTHORIZATION` will automatically randomly/round-robin to the next account |
| | CONVERSATION_ONLY | `false` | `false` | Whether to directly use the conversation interface. Enable only if your gateway supports automatic POW resolution |
| | ENABLE_LIMIT | `true` | `true` | When enabled, it will not attempt to bypass official request limits to minimize account suspension risk |
| | UPLOAD_BY_URL | `false` | `false` | When enabled, dialogue follows `URL+space+text`, automatically parsing and uploading URL content. Multiple URLs separated by spaces |
| | SCHEDULED_REFRESH | `false` | `false` | Whether to periodically refresh `AccessToken`. When enabled, all will be non-forcefully refreshed on startup, and forcefully refreshed at 3 AM every 4 days |
| | RANDOM_TOKEN | `true` | `true` | Whether to randomly select backend `Token`. Enabled for random backend account selection, disabled for sequential round-robin |
| Gateway | ENABLE_GATEWAY | `false` | `false` | Whether to enable gateway mode. When enabled, mirror sites can be used, but defenses will be lowered |
| | AUTO_SEED | `false` | `true` | Whether to enable random account mode. Enabled by default. After inputting `seed`, randomly match backend `Token`. Disable to manually interface for `Token` management |

## Deployment

### Zeabur Deployment

[![Deploy on Zeabur](https://zeabur.com/button.svg)](https://zeabur.com/templates/6HEGIZ?referralCode=LanQian528)

### Direct Deployment

```bash
git clone https://github.com/LanQian528/chat2api
cd chat2api
pip install -r requirements.txt
python app.py
```

### Docker Deployment

You need to install Docker and Docker Compose.

```bash
docker run -d \
  --name chat2api \
  -p 5005:5005 \
  lanqian528/chat2api:latest
```

### (Recommended, PLUS account compatible) Docker Compose Deployment

Create a new directory, for example, chat2api, and enter it:

```bash
mkdir chat2api
cd chat2api
```

Download the docker-compose.yml file from the repository in this directory:

```bash
wget https://raw.githubusercontent.com/LanQian528/chat2api/main/docker-compose-warp.yml
```

Modify the environment variables in the docker-compose-warp.yml file, then save:

```bash
docker-compose up -d
```

## Common Issues

> - Error Codes:
>   - `401`: Current IP does not support login-free access. Try changing IP address, setting proxy in `PROXY_URL` environment variable, or authentication failure.
>   - `403`: Check specific error message in logs.
>   - `429`: Current IP has exceeded hourly request limit. Wait and retry, or change IP.
>   - `500`: Internal server error, request failed.
>   - `502`: Server gateway error or network unavailable. Try changing network environment.

> - Known Situations:
>   - Many Japanese IPs do not support login-free access. Recommend using US IP for free GPT-3.5.
>   - 99% of accounts support free `GPT-4o`, but activation depends on IP region. Japan and Singapore IPs currently have higher activation probability.

> - What is the `AUTHORIZATION` environment variable?
>   - A self-set authentication for chat2api. Setting this allows using saved Tokens in rotation. Pass it as `APIKEY` during requests.
> - How to obtain AccessToken?
>   - Log in to ChatGPT official website, then open [https://chatgpt.com/api/auth/session](https://chatgpt.com/api/auth/session) to get the `accessToken` value.

## License

MIT License
