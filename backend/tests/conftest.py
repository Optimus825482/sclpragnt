"""Ortak pytest ayarları.

2026-10-17: TEYİT KURALI (`RADAR_NOTIFY_CONFIRM_RULE_ENABLED`, varsayılan açık) bildirim mekaniğini
sınayan eski testlerin tek kaynaklı örneklerini keserdi. Bu testler kuralı değil sessiz saat / cooldown /
push dürüstlüğü gibi mekanikleri sınar → test paketinde kural varsayılan KAPALI. Kuralın kendisi
`test_notification_policy.py::ConfirmRuleTests` içinde açıkça açılarak sınanır.
"""
import pytest


@pytest.fixture(autouse=True)
def _confirm_rule_off_by_default(request, monkeypatch):
    if request.node.cls is not None and request.node.cls.__name__ == "ConfirmRuleTests":
        return
    from app.config import config
    monkeypatch.setattr(config, "RADAR_NOTIFY_CONFIRM_RULE_ENABLED", False, raising=False)
