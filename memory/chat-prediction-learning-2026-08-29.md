---
name: chat-prediction-learning-2026-08-29
description: Chat M5/M15 tahminleri için ayrı tablo + Raporlar sekmesi + LLM
  postmortem öğrenme döngüsü eklendi
metadata:
  node_type: memory
  type: project
  originSessionId: sess_a4b152a1-8e9c-4ee7-a3af-efde0f591482
---

2026-08-29: Chat sayfasındaki M5/M15 yükseliş aday tahminleri için kendi kendini geliştirme hattı kuruldu.

- Yeni tablolar: `chat_predictions` (ayrı günlük, LLM postmortem alanlarıyla), `chat_prediction_insights` (türetilmiş dersler). Hem SQLite DDL (database.py init_db) hem PG şeması (migrations/001_pgvector_schema.sql) güncellendi. **Açık kalem:** PG modunda `init_db` şemayı her başlangıçta çalıştırdığından yeni tablolar bir sonraki backend restart ile oluşur.
- Yeni modül: `backend/app/chat_prediction_learning.py` — postmortem snapshot, JSON parse (tag normalize), `derive_insights` (min 5 örnek).
- Yeni döngü: `chat_prediction_learning_loop` (main.py, 120 sn) — kapanmış M1 ile sonuç ölçümü → LLM postmortem (tur başına max 6) → insight upsert → hafızaya `chat_prediction_insight` dokümanı.
- Sonuç ASLA LLM tarafından üretilmez (aynı kural [[scalper-v4-audit-2026-08-25]]); LLM yalnızca ölçülmüş sonucun nedenlerini etiketler.
- Enjeksiyon noktaları: `_detect_upside_candidates` (`learned_prediction_insights`), chat pipeline (`/api/strategies/llm/chat` context), sembol yorum tahmini (`/api/symbol-analysis/{symbol}/llm/commentary`).
- API: `/api/reports/chat-predictions`, `/api/reports/chat-predictions/insights`.
- **Replay testi (2026-08-29 2. tur):** `backend/app/chat_prediction_replay.py` + `GET /api/reports/chat-predictions/replay?lookback_hours=6&horizons=5,15&refresh=true` — canlı pipeline'ı geçmiş kapanmış 1m mumlarla yeniden koşar (resample→snapshot→_market_candidate_score benzeri skor→en iyi 3→M1 ile ölçüm). Arka plan job'ı, state polling. Sınırlar: canlı spread/derinlik/24h ticker geçmişi yok, Top-20 gainer taraması yerine aktif sembol listesi. Frontend: M5/M15 sekmesinde "Son 6 saat / Son 24 saat" butonları.
- **Tuzak:** `app/config.py`'da `from app.config import config` gerekli; `from app import config` çalışır ama instance attr'ları yoktur (modül-örneği karışıklığı) — pytest'te AttributeError verir.
- Testler: `tests/test_chat_prediction_learning.py` (6) + `tests/test_chat_prediction_replay.py` (7); tam suite 189 passed. pytest backend venv'ine kuruldu (`venv/Scripts/python.exe -m pytest`).
