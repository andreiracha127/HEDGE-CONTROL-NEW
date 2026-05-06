FROM python:3.11-slim AS builder

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt

RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r /app/requirements.txt

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home appuser

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

COPY backend /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "SCHEDULER_DISABLED=${SCHEDULER_DISABLED:-true} exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8000} --workers 2 --timeout 60"]
