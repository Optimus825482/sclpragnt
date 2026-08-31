# Geçici 403 teşhis: aktif LLM config + minik analiz çağrısı.
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import llm_analysis


async def main():
    cfg = await llm_analysis.database.get_active_llm_config()
    if not cfg:
        print("Aktif LLM config YOK")
        return
    print("model:", cfg["model"].get("name"))
    print("base_url:", cfg["provider"].get("base_url"))
    print("key_knocked:", bool(cfg["provider"].get("api_key_encrypted")))
    result = await llm_analysis.analyze({"type": "ping", "note": "minimal test", "symbol": "BTCTRY",
                                         "price": 1.0})
    print("analyze status:", result.get("status"))
    if result.get("error"):
        print("error:", result["error"][:300])
    elif result.get("text"):
        print("text:", result["text"][:200])


asyncio.run(main())
