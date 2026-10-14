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
# 2026-10-07 (P1-11 #4): Konteyner root olarak çalışıyordu. Uygulama ihlali
# başarılı olursa saldırgan root olurdu. UID/GID 10001 sabit ve yüksek
# seçildi: host'ta ayrıcalıklı bir kullanıcıyla çakışma olasılığı düşük ve
# bind-mount edilen volume'lar (bkz. docker-compose.yaml) bu UID'e
# chown/sahip verilerek yazılabilir kalır.
#
# KRİTİK SIRA: `mkdir /data` + `chown` USER'dan ÖNCE gelmeli; aksi halde
# entrypoint/migration /data'ya yazamaz (fail-closed). /app zaten COPY ile
# root sahipliğinde gelir; uygulama yalnızca okur, bu yüzden ayrıca chown
# GEREKMEZ (§ salt-okunur kod yüzeyi).
#
# ⚠️ MEVCUT KURULUM YÜKSELTMESİ: `scalper_data` volume'u eski (root) konteyner
# tarafından root sahipliğinde doldurulmuşsa, uid 10001 yazamaz ve özellikle
# ML_MODELS_DIR=/data/ml_models eğitimi başarısız olur. Tek seferlik düzeltme:
#   docker run --rm -v scalper_data:/data alpine chown -R 10001:10001 /data
RUN groupadd -g 10001 scalper \
    && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin scalper \
    && chown -R 10001:10001 /data
USER scalper
EXPOSE 8004
# 2026-09-28: --timeout-keep-alive=65 nginx keepalive (60s) ile eşleşir;
# backend tarafı nginx'ten ÖNCE bağlantıyı kapatmaz → broken pipe önlenir.
# --backlog=4096 startup sırasında biriken bağlantı kuyruğunu genişletir
# (varsayılan 2048 yetersiz kalabilir; kabul bekleyen istekler düşer → 502).
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004", "--timeout-keep-alive", "65", "--backlog", "4096"]
