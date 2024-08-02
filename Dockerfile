FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=5005
EXPOSE $PORT

CMD uvicorn app:app --host 0.0.0.0 --port $PORT
