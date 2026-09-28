# GLOBAL PROJESİ İÇİN COOLIFY TRAEFIK HEALTHCHECK GÜNCELLEME TALİMATI

**Tarih:** 2026-09-28  
**Hedef Repo:** Scalper Agent Global (`d:\scalperagent_global`)  
**Amaç:** Coolify üzerinde çıkan *"No health check configured. The resource may be functioning normally. Traefik and Caddy will route traffic to this container even without a health check..."* uyarısını çözmek ve Traefik proxy'sinin yalnızca servis hazır olduğunda trafik yönlendirmesini sağlamak.

---

## 1. YENİ OTURUMDA AJANA VERİLECEK TALİMAT (KOPYALA - YAPIŞTIR)

```markdown
Aşağıdaki Coolify Traefik Healthcheck ve Proxy izolasyonu düzeltmesini Global projemizin `docker-compose.yaml` dosyasına birebir uygula:

1. DIŞA AÇIK SERVİS (gateway_global):
   - `gateway_global` servisine Traefik loadbalancer healthcheck etiketlerini ekle:
     ```yaml
     labels:
       - "traefik.enable=true"
       - "traefik.http.services.gateway_global.loadbalancer.healthcheck.path=/gateway-health"
       - "traefik.http.services.gateway_global.loadbalancer.healthcheck.interval=10s"
       - "traefik.http.services.gateway_global.loadbalancer.healthcheck.timeout=3s"
     ```

2. İÇ SERVİSLERİN PROXY VE HEALTHCHECK UYARISINDAN İZOLE EDİLMESİ:
   - `postgres_global` servisine ekle:
     ```yaml
     exclude_from_hc: true
     labels:
       - "traefik.enable=false"
     ```
   - `backend_global` servisine ekle:
     ```yaml
     labels:
       - "traefik.enable=false"
     ```
   - `frontend_global` servisine ekle:
     ```yaml
     labels:
       - "traefik.enable=false"
     ```
   - `db-backup-global` servisine ekle:
     ```yaml
     exclude_from_hc: true
     labels:
       - "traefik.enable=false"
     ```

3. DOĞRULAMA:
   - python yaml kütüphanesi ile `docker-compose.yaml` dosyasının sözdizimini (syntax) doğrula.
   - Değişiklikleri commit edip GitHub'a push et.
```

---

## 2. DEĞİŞECEK DOSYA VE SATIRLAR (DOKÜMANTASYON)

Dosya: `d:\scalperagent_global\docker-compose.yaml`

### A. `postgres_global` servisi:
```yaml
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER_GLOBAL:-scalper} -d ${POSTGRES_DB_GLOBAL:-scalper_global}"]
      start_period: 30s
      interval: 10s
      timeout: 5s
      retries: 12
    exclude_from_hc: true
    labels:
      - "traefik.enable=false"
    logging: *default-logging
```

### B. `backend_global` servisi:
```yaml
      timeout: 12s
      retries: 10
    labels:
      - "traefik.enable=false"
    networks:
      - default
      - coolify
```

### C. `frontend_global` servisi:
```yaml
      start_period: 20s
      interval: 30s
      timeout: 5s
      retries: 3
    labels:
      - "traefik.enable=false"
    logging: *default-logging
```

### D. `gateway_global` servisi:
```yaml
    healthcheck:
      test: ["CMD-SHELL", "wget --spider -q http://127.0.0.1:80/gateway-health || exit 1"]
      start_period: 10s
      interval: 30s
      timeout: 5s
      retries: 3
    labels:
      - "traefik.enable=true"
      - "traefik.http.services.gateway_global.loadbalancer.healthcheck.path=/gateway-health"
      - "traefik.http.services.gateway_global.loadbalancer.healthcheck.interval=10s"
      - "traefik.http.services.gateway_global.loadbalancer.healthcheck.timeout=3s"
    logging: *default-logging
```

### E. `db-backup-global` servisi:
```yaml
          sleep 86400
        done
    exclude_from_hc: true
    labels:
      - "traefik.enable=false"
    logging: *default-logging
```

---

## 3. DEPLOY SONRASI COOLIFY'DA YAPILACAK İŞLEM
1. Coolify Dashboard'da Global uygulaması (**General** sekmesi) açılır.
2. **Reload Compose File** butonuna basılır (GitHub'dan güncel etiketler okunur).
3. **Redeploy** butonuna tıklanır.
