FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && python -c "import edge_tts; print('edge-tts hazır')"
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY .well-known ./.well-known
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh
RUN mkdir -p /data
ENV SCALPER_DB_PATH=/data/scalper_db_v4.sqlite
EXPOSE 8004
# 2026-09-28: --timeout-keep-alive=65 nginx keepalive (60s) ile eşleşir;
# backend tarafı nginx'ten ÖNCE bağlantıyı kapatmaz → broken pipe önlenir.
# --backlog=4096 startup sırasında biriken bağlantı kuyruğunu genişletir
# (varsayılan 2048 yetersiz kalabilir; kabul bekleyen istekler düşer → 502).
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004", "--timeout-keep-alive", "65", "--backlog", "4096"]
