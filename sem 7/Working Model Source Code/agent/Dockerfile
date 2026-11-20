# Quant Plus agent service (market data, Fyers feed, AI research).
# One process: the prediction cache, warming jobs and market feed are process-local.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QP_DB_PATH=/app/data/website.db
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app ./app
COPY quantplus_intelligence ./quantplus_intelligence
COPY contract ./contract
COPY scripts ./scripts
# Static reference lists only; caches, logs and broker tokens are created at runtime.
COPY data/nifty500.txt data/event_calendar.json ./data/
RUN mkdir -p /app/data && useradd --create-home quant && chown -R quant /app
USER quant
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
