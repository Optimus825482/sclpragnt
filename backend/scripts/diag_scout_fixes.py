# Geçici doğrulama: sanitize fix + memory context + LLM ping durumu.
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import llm_analysis
from app.memory_service import sanitize_retrieved_memory


def test_sanitize():
    # asyncpg jsonb string döndürdüğünde çökmemeli
    row = {"id": 1, "content": "örnek içerik", "metadata": "{\"source_type\":\"chat_message\"}"}
    out = sanitize_retrieved_memory(row)
    assert out["metadata"]["source_type"] == "chat_message", out
    assert out["provenance"]["source_type"] == "chat_message"
    # dict metadata da aynı şekilde çalışmalı
    out2 = sanitize_retrieved_memory({"id": 2, "content": "x", "metadata": {"source_type": "s"}})
    assert out2["metadata"]["source_type"] == "s"
    # bozuk JSON çökmemeli
    out3 = sanitize_retrieved_memory({"id": 3, "content": "x", "metadata": "{bozuk"})
    assert out3["metadata"] == {}
    print("sanitize_retrieved_memory: OK")


async def main():
    test_sanitize()
    cfg = await llm_analysis.database.get_active_llm_config()
    print("aktif model:", cfg["model"].get("name") if cfg else None)
    result = await llm_analysis.analyze({"type": "ping", "note": "minimal test", "symbol": "0GTRY",
                                         "price": 10.04, "instruction": "Tek cümlede 0GTRY fiyatını yaz."})
    print("analyze status:", result.get("status"))
    if result.get("error"):
        print("error:", result["error"][:200])
    elif result.get("text"):
        print("text:", result["text"][:150])


asyncio.run(main())
