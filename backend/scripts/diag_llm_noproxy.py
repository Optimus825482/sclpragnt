# Geçici: proxy env olmadan LLM ping (urllib proxy davranışı teşhisi).
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Komut ortamından sızabilecek proxy ayarlarını temizle.
for key in list(os.environ):
    if key.lower() in ("http_proxy", "https_proxy", "all_proxy", "ftp_proxy"):
        print("temizlendi:", key)
        os.environ.pop(key, None)

from app import llm_analysis


async def main():
    result = await llm_analysis.analyze({"type": "ping", "symbol": "0GTRY", "price": 10.04,
                                         "instruction": "Tek cümlede 0GTRY fiyatını yaz."})
    print("analyze status:", result.get("status"))
    if result.get("error"):
        print("error:", result["error"][:200])
    elif result.get("text"):
        print("text:", result["text"][:150])


asyncio.run(main())
