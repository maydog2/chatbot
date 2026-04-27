# FastAPI backend only. Build from repository root:
#   docker build -t companion-api .
# Run (set secrets via env / K8s Secret, not baked into the image):
#   docker run --rm -p 8000:8000 -e DB_URL=... -e AUTH_TOKEN_SECRET=... companion-api

FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --system --user-group app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8000

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/

RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn companion.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
