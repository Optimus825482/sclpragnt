"""Kısa yanıt politikası (2026-11-25): kullanıcı "kısaca açıkla" dedi.

Kural metni prompt'ta olmalı ve hızlı şerit çıktı tavanı küçültülmüş olmalı.
"""

from app.config import config
from app import llm_analysis


def test_brevity_budget_present_in_rules():
    rules = llm_analysis.OUTPUT_RULES
    assert "KISA YANIT BÜTÇESİ" in rules
    assert "en fazla 6 satır" in rules
    assert "SEMBOL SORUSU ŞABLONU" in rules
    # Şablonun dört satırı: durum / yukarı / aşağı / sonuç
    for label in ("Durum:", "Yukarı:", "Aşağı:", "Sonuç:"):
        assert label in rules, label


def test_brevity_rule_survives_admin_override():
    """Admin rolünde de uzunluk bütçesi geçerli olmalı (kullanıcı admin)."""
    admin_rules = llm_analysis.get_output_rules({"user_role": "admin"})
    assert "KISA YANIT BÜTÇESİ" in admin_rules
    assert "SEMBOL SORUSU ŞABLONU" in admin_rules


def test_quick_lane_output_cap_reduced():
    assert config.LLM_QUICK_LANE_MAX_TOKENS <= 1600, "hızlı şerit çıktısı kısaltılmalı"
    assert config.LLM_QUICK_LANE_MAX_TOKENS >= 128
