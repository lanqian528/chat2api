# CHAT2API

🤖 Một proxy đơn giản chuyển **ChatGPT thành API**

🌟 Dùng miễn phí, không cần tài khoản, không giới hạn với `GPT-3.5`

💥 Hỗ trợ AccessToken để dùng tài khoản, hỗ trợ `O3-mini/high`、`O1/mini/Pro`、`GPT-4/4o/mini`、`GPTs`

🔍 Định dạng phản hồi giống hệt API thật, tương thích hầu hết client

👮 Đi kèm bảng điều khiển quản lý người dùng [Chat-Share](https://github.com/h88782481/Chat-Share) – trước khi dùng cần cấu hình biến môi trường (ENABLE_GATEWAY = True, AUTO_SEED = False)

## Nhóm thảo luận

[https://t.me/chat2api](https://t.me/chat2api)

Khi hỏi đáp, vui lòng đọc hết tài liệu repo trước, đặc biệt phần FAQ.

Thông tin cần cung cấp khi đặt câu hỏi:

1. Ảnh chụp log khởi động (nhớ che thông tin nhạy cảm như biến môi trường, version)
2. Log lỗi chi tiết (nhớ che thông tin nhạy cảm)
3. Mã trạng thái và response body của API

## Tính năng

### Phiên bản mới nhất lưu ở `version.txt`

### Chức năng API đảo ngược

> * [x] Truyền dữ liệu dạng stream hoặc non-stream
> * [x] GPT-3.5 miễn đăng nhập
> * [x] GPT-3.5 (nếu model name không chứa gpt-4 thì mặc định dùng gpt-3.5: text-davinci-002-render-sha)
> * [x] GPT-4 series (gpt-4, gpt-4o, gpt-4o-mini, gpt-4-mobile, cần AccessToken)
> * [x] O1 series (o1-preview, o1-mini, cần AccessToken)
> * [x] GPT-4 có thể vẽ hình, viết code, truy cập Internet
> * [x] Hỗ trợ GPTs (gpt-4-gizmo-g-*)
> * [x] Hỗ trợ Team Plus account (cần account id)
> * [x] Upload ảnh, file (hỗ trợ URL và base64)
> * [x] Có thể dùng làm Gateway, hỗ trợ phân tán multi-server
> * [x] Multi-account round robin, hỗ trợ `AccessToken` & `RefreshToken`
> * [x] Retry request lỗi, tự động chuyển token khác
> * [x] Quản lý Tokens (upload, clear)
> * [x] Refresh định kỳ AccessToken bằng RefreshToken (khởi động sẽ refresh một lần, 4 ngày 1 lần refresh toàn bộ lúc 3h sáng)
> * [x] Hỗ trợ tải file (cần bật lịch sử)
> * [x] Hỗ trợ output quá trình suy luận `O3-mini/high`、`O1/mini/Pro`

### Chức năng bản mirror web gốc

> * [x] Hỗ trợ mirror native trang chủ
> * [x] Random account từ account pool với `Seed`
> * [x] Nhập RefreshToken hoặc AccessToken để đăng nhập
> * [x] Hỗ trợ `O3-mini/high`、`O1/mini/Pro`、`GPT-4/4o/mini`
> * [x] Ẩn các API nhạy cảm, disable một số setting
> * [x] /login để login, logout xong tự redirect về login
> * [x] /?token=xxx login trực tiếp (xxx là RefreshToken, AccessToken hoặc SeedToken)
> * [x] Hỗ trợ cách ly session theo SeedToken
> * [x] Hỗ trợ cửa hàng GPTs
> * [x] Hỗ trợ DeepResearch, Canvas (tính năng riêng của web gốc)
> * [x] Hỗ trợ nhiều ngôn ngữ giao diện

> TODO:
>
> * [ ] Chưa có, chào đón góp `issue`

## API đảo ngược

API format giống hệt `OpenAI` , hỗ trợ AccessToken hoặc RefreshToken, dùng được GPT-4, GPT-4o, GPT-4o-Mini, GPTs, O1-Pro, O1, O1-Mini, O3-Mini, O3-Mini-High:

```bash
curl --location 'http://127.0.0.1:5005/v1/chat/completions' 
--header 'Content-Type: application/json' 
--header 'Authorization: Bearer {{Token}}' 
--data '{
     "model": "gpt-3.5-turbo",
     "messages": [{"role": "user", "content": "Say this is a test!"}],
     "stream": true
   }'
```

* Dùng AccessToken hoặc RefreshToken thay cho `{{ Token }}`.
* Hoặc điền giá trị biến môi trường `Authorization`, hệ thống sẽ chọn account random.
* Nếu có Team account, truyền thêm `ChatGPT-Account-ID`.

Chi tiết cách truyền ID:

* Cách 1: thêm header `ChatGPT-Account-ID`
* Cách 2: `Authorization: Bearer <AccessToken|RefreshToken>,<ChatGPT-Account-ID>`

### Token Management

1. Cấu hình biến môi trường `AUTHORIZATION` làm key, chạy chương trình
2. `/tokens` hoặc `/{api_prefix}/tokens` để xem, upload hoặc clear tokens
3. Request truyền `AUTHORIZATION` key → sẽ tự động round robin tokens

![tokens.png](docs/tokens.png)

### Bản mirror web gốc

1. `ENABLE_GATEWAY = true`, chạy chương trình
2. Upload RefreshToken hoặc AccessToken trong trang tokens
3. Truy cập `/login` để login
4. Sử dụng bản mirror web

---

## Environment Variables (biến môi trường)

| Nhóm     | Tên biến           | Giá trị mẫu           | Mặc định              | Mô tả                                            |
| -------- | ------------------ | --------------------- | --------------------- | ------------------------------------------------ |
| Bảo mật  | API_PREFIX         | `your_prefix`         | None                  | API prefix password, tránh bị truy cập công khai |
|          | AUTHORIZATION      | `key1,key2`           | []                   | Key tự đặt để round robin tokens                 |
|          | AUTH_KEY           | `your_auth_key`       | None                  | Nếu muốn gateway private, thêm header này        |
| Request  | CHATGPT_BASE_URL   | `https://chatgpt.com` | `https://chatgpt.com` | URL ChatGPT gateway                              |
|          | PROXY_URL          | `http://ip:port`      | []                   | Proxy toàn cục (tránh 403)                       |
|          | EXPORT_PROXY_URL   | `http://ip:port`      | None                  | Proxy xuất, bảo vệ IP khi tải ảnh/file           |
| Features | HISTORY_DISABLED   | `true`                | `true`                | Có lưu lịch sử hội thoại không                   |
|          | POW_DIFFICULTY     | `00003a`              | `00003a`              | Độ khó POW                                       |
|          | RETRY_TIMES        | `3`                   | `3`                   | Số lần retry request lỗi                         |
|          | CONVERSATION_ONLY  | `false`               | `false`               | Chỉ dùng conversation API                        |
|          | ENABLE_LIMIT       | `true`                | `true`                | Không vượt giới hạn official                     |
|          | UPLOAD_BY_URL      | `false`               | `false`               | Tự parse URL + text để upload                    |
|          | SCHEDULED_REFRESH  | `false`               | `false`               | Refresh AccessToken định kỳ                      |
|          | RANDOM_TOKEN       | `true`                | `true`                | Chọn token random thay vì tuần tự                |
| Gateway  | ENABLE_GATEWAY     | `false`               | `false`               | Bật chế độ gateway/mirror                        |
|          | AUTO_SEED          | `false`               | `true`                | Bật random account bằng seed                     |

---

## Deploy

### Deploy qua Zeabur

[![Deploy on Zeabur](https://zeabur.com/button.svg)](https://zeabur.com/templates/6HEGIZ?referralCode=LanQian528)

### Deploy trực tiếp

```bash
git clone https://github.com/LanQian528/chat2api
cd chat2api
pip install -r requirements.txt
python app.py
```

### Deploy Docker

```bash
docker run -d 
  --name chat2api 
  -p 5005:5005 
  lanqian528/chat2api:latest
```

### Deploy Docker Compose (khuyên dùng, hỗ trợ Plus account)

```bash
mkdir chat2api
cd chat2api
wget https://raw.githubusercontent.com/LanQian528/chat2api/main/docker-compose-warp.yml
docker-compose up -d
```

---

## FAQ

* **401**: IP không hỗ trợ free-login hoặc token lỗi → đổi IP, set PROXY_URL, hoặc check auth

* **403**: Xem log chi tiết

* **429**: Rate limit (1h quá nhiều request)

* **500**: Server internal error

* **502**: Gateway error hoặc network lỗi

* **Lưu ý:**

  * IP Nhật nhiều khi không hỗ trợ free GPT-3.5 → dùng IP US tốt hơn
  * 99% account có GPT-4o free, nhưng tùy IP (Nhật/Singapore dễ bật hơn)

---

## License

MIT License
