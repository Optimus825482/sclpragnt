# Coolify/Traefik — "no available server" Teşhisi

Gözlendi (2026-09-27): deploy başarılı ve tüm container logları temiz olduğu
halde `https://scalper.erkanerdem.online` dışarıdan **"no available server"**
dönüyor.

## Mimari (hedef)
- Traefik (coolify-proxy), `coolify` ağındaki container'lara route oluşturur.
- `docker-compose.yaml`'de **yalnızca `gateway`** servisi `coolify` ağına bağlı
  (`networks: default + coolify`); `frontend` ve `backend` yalnız `default` ağında.
- README.md:120: domain **`gateway` servisine, port 80**'e bağlanmalı.
- Gateway = nginx; `/api`, `/health`, `/ws` → backend (`backend:8004`),
  geri kalan → frontend (`frontend:3004`).

## Kök neden (büyük olasılık)
Coolify, docker-compose kaynaklarında domain etiketini **compose'daki ilk
servise** (varsayılan: `postgres`) uygular. `postgres` `coolify` ağında
olmadığından Traefik için "no available server" oluşur. Doğru hedef:
`gateway:80`.

## Kök neden #2 (2026-10-12) — çok ağlı gateway + eksik Traefik etiketleri
Log'da gateway (nginx) sağlıklı çalışırken dışarıdan hâlâ "no available server"
görüldü. Neden **gateway'in kendi Traefik tanımıydı**, frontend portu değil:

1. **`traefik.docker.network` YOKTU.** Gateway hem `default` hem `coolify`
   ağındadır. Traefik'e hedef ağ söylenmezse, çok ağlı konteynerin IP'sini
   ağların dönüş sırasına göre **rastgele** seçer. `default` seçilirse proxy o
   IP'ye ulaşamaz → router var ama arkasında sağlıklı sunucu yok.
2. **`loadbalancer.server.port` YOKTU.** Traefik servisin portunu bilemezse
   servisi oluşturamaz.

İkisi birlikte `docker-compose.yaml` gateway etiketlerine eklendi:
`traefik.docker.network=coolify` + `...loadbalancer.server.port=80`.
Regresyon kilidi: `backend/tests/test_regressions.py::
test_compose_traefik_routing_targets_gateway_correctly`.

## Doğrulama (sunucu)
```bash
# 1) Proxy ağ adı gerçekten 'coolify' mı?
docker network ls | grep -i coolify

# 2) Gateway hangi ağlarda? ('coolify' görünmeli)
docker inspect $(docker ps --filter name=gateway-a119 -q) --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'

# 3) Traefik domain için router üretmiş mi ve hangi servise işaret ediyor?
docker logs coolify-proxy --tail 200 2>&1 | grep -iE "scalper|erkanerdem|server|router|error"

# 4) Gateway içinden upstream erişimi (içeride her şey sağlıklı mı?)
docker exec <gateway_konteyner> wget -qO- http://backend:8004/health
docker exec <gateway_konteyner> wget -qO- http://frontend:3004/ | head
```

## Düzeltme
- Coolify → ilgili docker-compose uygulaması → **Domains/Routes**:
  `scalper.erkanerdem.online` → **`gateway` servisi, port `80`**.
- Kaydet → Redeploy/Restart → `curl -I https://scalper.erkanerdem.online`
  ile `200` bekle.

## İlgisiz ama logda görülen gerçek hata
`auto_paper_trades WHERE notification_id=$1` → "reopen:WLDTRY:497358"
(string, `bigint` kolona). "no available server" ile ilgisiz; reopen akışında
ayrı bir tip hatası.