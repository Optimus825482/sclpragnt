FROM nginx:1.27-alpine

# 2026-10-07 (P1-11 #4): Gateway master process root olarak çalışıyordu.
# Non-root'a indirmek için üç şey gerekir:
#   1) nginx binary'sine port 80 bağlama yetkisi (CAP_NET_BIND_SERVICE) —
#      aksi halde non-root master <1024 portunu dinleyemez. `setcap` bunu
#      root olmadan verir; imaj katmanında xattr olarak saklanır.
#   2) nginx kullanıcısının YAZACAĞI dizinler: cache ve pid. Varsayılan
#      `pid /var/run/nginx.pid;` ve /var/cache/nginx root sahipliğinde
#      olduğundan master açılışta yazamaz → "permission denied" ile ölür.
#   3) Varsayılan worker zaten `nginx`; artık MASTER da `nginx` (USER sonrası).
# Port 80 KORUNUR (Traefik/Coolify routing bu porta bağlıdır) — yalnız
# yetki kabiliyeti eklenir, dinlenen port değiştirilmez.
RUN apk add --no-cache libcap \
    && setcap 'cap_net_bind_service=+ep' /usr/sbin/nginx \
    && mkdir -p /var/cache/nginx/client_temp /var/cache/nginx/proxy_temp \
       /var/cache/nginx/fastcgi_temp /var/cache/nginx/uwsgi_temp /var/cache/nginx/scgi_temp \
    && chown -R nginx:nginx /var/cache/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid

COPY default.conf /etc/nginx/conf.d/default.conf

USER nginx
