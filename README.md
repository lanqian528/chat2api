# CHAT2API

免费的GPT3.5 api

### 注：仅ip属地支持免登录使用ChatGpt可以使用

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

## 高级设置

默认情况不需要设置，除非你有需求

### 环境变量

```
PROXY_URL=http://username:password@proxy:port
CHATGPT_BASE_URL=https://chat.openai.com/backend-anon
HISTORY_DISABLED=true
```

[//]: # (## 鸣谢)

[//]: # ()

[//]: # (感谢各位大佬的pr支持，感谢。)

## License

MIT License
