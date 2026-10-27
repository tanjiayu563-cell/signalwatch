FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MONITOR_HOST=0.0.0.0 \
    MONITOR_PORT=8765 \
    MONITOR_DATA_DIR=/app/data \
    MONITOR_DB_PATH=/app/data/monitor.db \
    MONITOR_CREDENTIAL_PATH=/app/data/credentials.json

WORKDIR /app

RUN addgroup --system signalwatch \
    && adduser --system --ingroup signalwatch --home /app signalwatch \
    && mkdir -p /app/data \
    && chown -R signalwatch:signalwatch /app

COPY --chown=signalwatch:signalwatch app.py ./
COPY --chown=signalwatch:signalwatch monitor_agent ./monitor_agent
COPY --chown=signalwatch:signalwatch static ./static
COPY --chown=signalwatch:signalwatch eval ./eval
COPY --chown=signalwatch:signalwatch scripts ./scripts

USER signalwatch

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3).read()"

CMD ["python3", "app.py"]
