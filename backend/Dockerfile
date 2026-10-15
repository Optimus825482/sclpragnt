# 2026-10-15 (denetim düzeltmesi, §5 P2): taban imaj Debian sürümüne
# sabitlendi (`python:3.11-slim` bir sonraki Debian'a sessizce kayabilir;
# PGDG deposu dağıtım adına bağlıdır). sha256 digest sabitlemesi ağ
# erişimi olmadan yapılamadı — tag sabitleme ile yetinildi.
FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
# 2026-10-15 (denetim düzeltmesi, §5 P2): Debian bookworm'un kendi
# `postgresql-client` paketi PostgreSQL 15'tir; stack'teki sunucu ise
# pg17 (`pgvector/pgvector:pg17-bookworm`). pg_dump sunucudan ESKİ sürümde
# "server version mismatch" ile reddeder → /api/system/backup (main.py)
# ve database.py'deki pg_dump yolu kırılırdı. PGDG (apt.postgresql.org)
# deposundan `postgresql-client-17` kurulur. İmza anahtarı ASCII-armored
# olarak `signed-by` ile verilir (apt ≥ 1.4 destekler; gnupg/curl kurmaya
# gerek yok — indirme imajdaki Python ile yapılır, ca-certificates hazır).
RUN install -d -m 0755 /etc/apt/keyrings \
    && python -c "import urllib.request; urllib.request.urlretrieve('https://www.postgresql.org/media/keys/ACCC4CF8.asc', '/etc/apt/keyrings/postgresql.asc')" \
    && echo "deb [signed-by=/etc/apt/keyrings/postgresql.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/* \
    && pg_dump --version \
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
# 2026-10-15 (denetim düzeltmesi, §5 P1/P2): imaj düzeyinde HEALTHCHECK —
# docker-compose.yaml'daki backend healthcheck'i ile BİREBİR aynı değerler
# (compose tanımı varsa onu ezer; `docker run` ile tek başına çalışırken de
# aynı sözleşme geçerli olsun). timeout (12) ≥ urlopen timeout (10).
# /health döngü kaydına bakar ve 503 dönebilir; urlopen 503'te HTTPError
# fırlatır → çıkış kodu 1 → unhealthy (bkz. routers/system.py).
HEALTHCHECK --interval=20s --timeout=12s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8004/health', timeout=10)"
# 2026-10-14 (RAM/performans optimizasyonu):
#  * --loop uvloop: uvicorn[standard] zaten uvloop içerir; libuv tabanlı
#    event loop istek/WS fanout'ta asyncio varsayılanından belirgin hızlıdır.
#  * --http httptools: HTTP ayrıştırıcı C ile yazılmış; yüksek istek hacminde
#    CPU kazandırır. (İkisi de requirements'ta zaten var, yeni bağımlılık YOK.)
#  * --no-access-log: erişim logu gateway (nginx) tarafında zaten tutuluyor;
#    backend'de tekrarı yüksek tarama trafiğinde gereksiz IO + RAM demekti.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004", "--timeout-keep-alive", "65", "--backlog", "4096", "--loop", "uvloop", "--http", "httptools", "--no-access-log"]
