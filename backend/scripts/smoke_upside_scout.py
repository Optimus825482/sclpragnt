# Geçici upside-scout smoke: endpoint fonksiyonunu doğrudan çağırır (gerçek LLM çağrısı).
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.routers.llm_chat import llm_upside_scout


async def main():
    result = await llm_upside_scout({})
    print("status:", result.get("status"), "| symbol:", result.get("symbol"),
          "| model:", result.get("model"))
    sel = result.get("selection") or {}
    if sel:
        print(json.dumps(sel, ensure_ascii=False, indent=2, default=str))
    text = result.get("analysis") or ""
    print("\n--- ANALIZ (ilk 1200 karakter) ---")
    print(text[:1200])
    if result.get("error"):
        print("ERROR:", result["error"])


asyncio.run(main())
