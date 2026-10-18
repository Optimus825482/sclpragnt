"""Ortak pytest ayarları.

2026-10-17: TEYİT KURALI (`RADAR_NOTIFY_CONFIRM_RULE_ENABLED`, varsayılan açık) bildirim mekaniğini
sınayan eski testlerin tek kaynaklı örneklerini keserdi. Bu testler kuralı değil sessiz saat / cooldown /
push dürüstlüğü gibi mekanikleri sınar → test paketinde kural varsayılan KAPALI. Kuralın kendisi
`test_notification_policy.py::ConfirmRuleTests` içinde açıkça açılarak sınanır.
"""
import pytest


_RULE_TEST_CLASSES = {"ConfirmRuleTests", "SingleSourceTierTests", "HeartbeatTests"}


@pytest.fixture(autouse=True)
def _confirm_rule_off_by_default(request, monkeypatch):
    if request.node.cls is not None and request.node.cls.__name__ in _RULE_TEST_CLASSES:
        return
    from app.config import config
    monkeypatch.setattr(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", False, raising=False)
    # 2026-10-18: ikinci kademe ve sessizlik nabzı da mekanik testlerde kapalı (kendi sınıflarında açık).
    monkeypatch.setattr(config, "RADAR_NOTIFY_SINGLE_SOURCE_MIN_SCORE", 0.0, raising=False)
    monkeypatch.setattr(config, "RADAR_NOTIFY_HEARTBEAT_MINUTES", 0, raising=False)
    # 2026-10-18: bildirim sayıları dürüstleştirme bayrakları. Eski testler ZİNCİR hedefini (skor kademesi,
    # net-kâr tabanı, öğrenilmiş hedef, ML karışımı) ve eski kapıları sınar → paket varsayılanı eski davranış;
    # yeni davranış `test_notify_metrics.py` içinde bayraklar AÇIKÇA kurularak sınanır.
    monkeypatch.setattr(config, "RADAR_TARGET_MODE", "chain", raising=False)
    # 2026-10-18: net hedef tabanı ve gönderim sonrası donma da eski testlerde KAPALI (kendi sınıflarında açık).
    monkeypatch.setattr(config, "RADAR_TARGET_MIN_NET_PCT", 0.0, raising=False)
    monkeypatch.setattr(config, "RADAR_NOTIFY_FREEZE_ON_SEND", False, raising=False)
    # 2026-10-18: otonom hız avcısı girişinin push şartı eski testlerde KAPALI (kendi sınıfında açık).
    monkeypatch.setattr(config, "AUTO_PAPER_ONLY_ON_PUSH", False, raising=False)
    monkeypatch.setattr(config, "RADAR_TARGET_ML_BLEND_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "RADAR_NOTIFY_SHOW_ML_PROB", True, raising=False)
    monkeypatch.setattr(config, "RADAR_FUSION_TARGET_DYNAMIC", False, raising=False)
