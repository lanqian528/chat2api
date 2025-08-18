from openai import OpenAI
from time import time 

client = OpenAI(
    base_url="http://127.0.0.1:5005/v1",  # có /pp vì API_PREFIX=pp
    #api_key=""
    api_key="eyJhbGciOiJSUzI1NiIsImtpZCI6IjE5MzQ0ZTY1LWJiYzktNDRkMS1hOWQwLWY5NTdiMDc5YmQwZSIsInR5cCI6IkpXVCJ9.eyJhdWQiOlsiaHR0cHM6Ly9hcGkub3BlbmFpLmNvbS92MSJdLCJjbGllbnRfaWQiOiJhcHBfWDh6WTZ2VzJwUTl0UjNkRTduSzFqTDVnSCIsImV4cCI6MTc1NjE5MzMzOCwiaHR0cHM6Ly9hcGkub3BlbmFpLmNvbS9hdXRoIjp7InVzZXJfaWQiOiJ1c2VyLVVlU3g5UXhQUlNtNk9kdXA2WGtFUFRPciJ9LCJodHRwczovL2FwaS5vcGVuYWkuY29tL3Byb2ZpbGUiOnsiZW1haWwiOiJtb3N0Z29uM0BnbWFpbC5jb20iLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZX0sImlhdCI6MTc1NTMyOTMzOCwiaXNzIjoiaHR0cHM6Ly9hdXRoLm9wZW5haS5jb20iLCJqdGkiOiIwY2IxNjRjZi1hNGNkLTQ1NTktYTYzZC1iNThkYjE5OGM4ZTAiLCJuYmYiOjE3NTUzMjkzMzgsInB3ZF9hdXRoX3RpbWUiOjE3NTUzMjkzMzY2MjgsInNjcCI6WyJvcGVuaWQiLCJlbWFpbCIsInByb2ZpbGUiLCJvZmZsaW5lX2FjY2VzcyIsIm1vZGVsLnJlcXVlc3QiLCJtb2RlbC5yZWFkIiwib3JnYW5pemF0aW9uLnJlYWQiLCJvcmdhbml6YXRpb24ud3JpdGUiXSwic2Vzc2lvbl9pZCI6ImF1dGhzZXNzX3g4WlFLekk0Z1ZQUzlMZlFWMzF1QW9IdyIsInN1YiI6Imdvb2dsZS1vYXV0aDJ8MTA1NzkyNzMzMDk0MDc5MzI0ODk2In0.LMUPHV3ptsljO6cUP5rFEE2bFdTxRBk1jx8TCc4wYzJw6uBjFafXtPqLcCy3xgcBtY5cLTJKsndSITwZPAPEdjSIwvVqCjmxQahqtBoUF4nI96PY7uIATIvnHi6uo3MDsj_A_OISrcxWKxJD7wu1daQvy9WjnJmWS6raP7CpCSMSYJmakKDtSy9q2BaqtNluh05PalnrNF1WhWpigZ3t1ei-0BPLvYLRUWRLRcI5QJPSljOIMFv1tH12nM8dNUNpHpUWhHR9AuT8Mlx2wLjxS9Yc-MFzAW8AC6W6eZLMWUzrTenIrt0g0NCPmX9aLhd_1LDfxCgacifw-TFjEw0ju4Z5b-xYc2lfrf_5tsgXEp_tukEaXTyGhCjZHLAdgryiDNNrBxUTkaJweUKbCwY5wKRTTpIdzivmameMEEXbMd9Ex5RLUBQ6mMqee1jg4dGuWa3hfv3gvgpzzB5IjuzbeX6R_4FUtTRGlB5xIuaTIq76-h2PTzZhrxS-xKX7fF8_t01FXNMSA1IdpNz5ifjRViEZR69hqRoolKEAWMq9RACMEPLos7WeEPSrh3tLs2rUxQ4y4g1ydgCyO8ZujvYA6oQOTXxdaYBJBVsABs2GfuyygbtokJdTRnWEbcUVdYir9LgK5ze4vDqscxchI4PHPOBLVeL0UwtNAIG5DDarO7s"                     # trùng AUTHORIZATION
)

start = time()

response = client.chat.completions.create(
  model="gpt-5",
  messages=[
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Xin chào bạn của tôi!!"}
  ],
  stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content, end="", flush=True)

# stream = client.responses.create(
#     model="gpt-5",
#     input=[
#         {
#             "role": "user",
#             "content": "Say 'double bubble bath' ten times fast.",
#         },
#     ],
#     stream=True,
#     store=False,
# )

# for event in stream:
#     print(event.output_text, end="", flush=True)

end = time()
print(f"Response time: {end - start} seconds")