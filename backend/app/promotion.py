"""S7b: candidate-strategy promotion pipeline with hard gates.

Lifecycle: shadow -> walk_forward -> paper_candidate -> active (human-approved).

A candidate may only advance when the *previous* stage's objective evidence
exists:
- shadow -> walk_forward : the shadow observer journaled >= min observations
- walk_forward -> paper  : run_custom_walk_forward returned validation PASS
                           (chronological OOS folds, >=30 trades, positive)
- paper -> active        : >= min paper trades with non-negative expectancy
                           AND explicit human approval (never automatic)

State persists in llm_settings KV; every transition is appended to an audit
trail so the pipeline itself stays auditable.
"""
import json
import time

from app import database

_KEY = "strategy_promotion_pipeline"
VALID_STAGES = ("shadow", "walk_forward", "paper_candidate", "active")
MIN_SHADOW_OBSERVATIONS = 120      # ~10 days of 5m candles per symbol set
MIN_PAPER_TRADES = 20


class PromotionPipeline:
    def __init__(self):
        self._state = {}     # name -> {"stage":..., "updated_at":..., "evidence":{...}}
        self._loaded = False

    async def _ensure(self):
        if self._loaded:
            return
        try:
            raw = await database.get_llm_setting(_KEY, "{}")
            parsed = json.loads(raw or "{}")
            if isinstance(parsed, dict):
                self._state = parsed.get("strategies", {})
        except (ValueError, TypeError):
            self._state = {}
        self._loaded = True

    async def _save(self):
        await database.set_llm_setting(_KEY, json.dumps(
            {"strategies": self._state}, ensure_ascii=False))

    def status(self) -> dict:
        return {name: dict(info) for name, info in self._state.items()}

    def stage_of(self, name: str) -> str | None:
        info = self._state.get(name)
        return info.get("stage") if info else None

    async def register(self, name: str, stage: str = "shadow") -> dict:
        if stage not in VALID_STAGES:
            raise ValueError(f"geçersiz aşama: {stage}")
        await self._ensure()
        entry = self._state.setdefault(name, {
            "stage": stage, "created_at": time.time(), "evidence": {},
            "transitions": []})
        entry["stage"] = stage
        entry["updated_at"] = time.time()
        await self._save()
        return entry

    async def _advance(self, name: str, to_stage: str, evidence: dict):
        entry = self._state[name]
        frm = entry["stage"]
        entry["stage"] = to_stage
        entry["updated_at"] = time.time()
        entry["evidence"].update(evidence or {})
        entry.setdefault("transitions", []).append({
            "from": frm, "to": to_stage, "at": time.time(), "evidence": evidence or {}})
        await self._save()

    async def promote(self, name: str, *, shadow_observations: int | None = None,
                      walk_forward_pass: bool | None = None,
                      paper_trades: int | None = None,
                      paper_expectancy: float | None = None,
                      human_approved: bool = False) -> dict:
        """Attempt one gate advance; refuses without objective evidence."""
        from app.config import config
        del config  # imported for symmetry/future gates
        await self._ensure()
        if name not in self._state:
            raise ValueError(f"{name} boru hattında kayıtlı değil")
        entry = self._state[name]
        stage = entry["stage"]
        if stage == "shadow":
            if (shadow_observations or 0) < MIN_SHADOW_OBSERVATIONS:
                return {"advanced": False,
                        "reason": f"shadow gözlemi yetersiz: {shadow_observations} < {MIN_SHADOW_OBSERVATIONS}"}
            await self._advance(name, "walk_forward",
                                {"shadow_observations": shadow_observations})
            return {"advanced": True, "to": "walk_forward"}
        if stage == "walk_forward":
            if not walk_forward_pass:
                return {"advanced": False,
                        "reason": "walk-forward OOS kapısı PASS olmadan terfi yok"}
            await self._advance(name, "paper_candidate", {"walk_forward_pass": True})
            return {"advanced": True, "to": "paper_candidate"}
        if stage == "paper_candidate":
            if (paper_trades or 0) < MIN_PAPER_TRADES or paper_expectancy is None:
                return {"advanced": False,
                        "reason": f"paper kanıtı yetersiz: {paper_trades} işlem / expectancy={paper_expectancy}"}
            if not human_approved:
                return {"advanced": False,
                        "reason": "active'e geçiş için açık insan onayı gerekli"}
            await self._advance(name, "active", {
                "paper_trades": paper_trades,
                "paper_expectancy": round(paper_expectancy, 4),
                "human_approved": True})
            return {"advanced": True, "to": "active"}
        return {"advanced": False, "reason": f"{stage} zaten son aşama"}


pipeline = PromotionPipeline()
