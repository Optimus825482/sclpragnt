"""Çevrimdışı (offline) Hız Avcısı yeniden taraması — saf çekirdek.

`scripts/rescan_velocity_history.py` bu paketi kullanır. Paket DB'ye, ağa ve
çalışma zamanı durumuna (market/orderflow/microflow/ML) DOKUNMAZ; canlı
dedektörün saf fonksiyonları `app.routers.velocity`'den içe aktarılır.
"""
