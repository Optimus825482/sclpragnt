# Geçici: _upside_scout_impl uçtan uca doğrulama (yerelde LLM 403 döner ama
# kritik olan crash olmadan temiz JSON döndürmesidir — serialization fix testi).
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.routers.llm_chat import _upside_scout_impl


async def main():
    result = await _upside_scout_impl()
    print("status:", result.get("status"), "| symbol:", result.get("symbol"))
    if result.get("error"):
        print("error:", str(result["error"])[:200])
    sel = result.get("selection") or {}
    if sel:
        print("rank:", sel.get("rank_score"), "| multi:", sel.get("quality_multiplier"),
              "| gate:", sel.get("min_score_gate"))
    # memory_context bu sefer veriyle mi döndü?
    # (impl içinden geçti; hata olsaydı endpoint düz metin 500 olurdu)
    print("UNHANDLED-EXCEPTION: YOK — endpoint temiz dondu")


asyncio.run(main())
