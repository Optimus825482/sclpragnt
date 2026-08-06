import asyncio, base64, json, os, time
from urllib.request import Request, urlopen
from cryptography.fernet import Fernet
from app import database

PERSONA = """Persona adın Scalper. Kullanıcının adı Erkan'dır; ona Türkçe, doğrudan ve teknik bir çalışma arkadaşı gibi hitap edersin. Erkan'ın talimatlarını mevcut sistem kapsamı içinde uygularsın; kimlik, yetki veya kişisel bilgi uydurmazsın. Paper-trading güvenlik kurallarını aşmayı önermezsin."""
OUTPUT_RULES = """ÇIKTI BİÇİMİ KURALLARI:
- Türkçe kelimeler arasındaki boşlukları mutlaka koru; kelimeleri veya cümleleri birleştirme.
- Yanıtı okunabilir Markdown olarak yaz: ana bölümler için `### Başlık`, maddeler için `- madde` kullan.
- Her cümle arasında normal boşluk bırak; sembol, sayı, yüzde ve birim değerlerini ayırarak yaz (ör. `8.97 TRY`, `%0.25`).
- Ham JSON, HTML veya tek satır sıkıştırılmış metin üretme.
- `market_scan` verildiğinde tüm taranan sembolleri karşılaştır; yükseliş ve yüksek skor adaylarını çoklu timeframe kanıtlarıyla derinleştir.
- Kullanıcı işlem önerisi istediğinde yalnızca paper-trading senaryosu sun: giriş bölgesi, teyit, invalidasyon/stop, hedef, risk ve güven seviyesi. Gerçek emir veya kesin kâr vaadi verme.
"""

def _decode_provider_response(raw):
    """Decode normal JSON, NDJSON and providers that append a second JSON object."""
    if isinstance(raw, (dict, list)): return raw
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else str(raw)
    text = text.strip()
    try: return json.loads(text)
    except json.JSONDecodeError as first_error:
        decoder = json.JSONDecoder()
        objects = []
        cursor = 0
        while cursor < len(text):
            while cursor < len(text) and text[cursor].isspace(): cursor += 1
            if cursor >= len(text): break
            try:
                item, end = decoder.raw_decode(text, cursor)
                objects.append(item); cursor = end
            except json.JSONDecodeError:
                # Ignore non-JSON trailing log/proxy text after a valid object.
                if objects: break
                raise first_error
        if len(objects) == 1: return objects[0]
        for item in objects:
            candidate = item.get("data", item) if isinstance(item, dict) else item
            if isinstance(candidate, dict) and (candidate.get("choices") or candidate.get("output_text") or candidate.get("response")):
                return candidate
        return objects[0] if objects else text

def _decode_json_value(value, label="JSON"):
    """Accept dicts, fenced JSON, NDJSON and provider JSON-string arguments."""
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    text = str(value).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
    try:
        return _decode_provider_response(text)
    except Exception as exc:
        raise ValueError(f"{label} çözümlenemedi: {exc}") from exc

def _message_text(message):
    """Normalize OpenAI-compatible content strings and content block arrays."""
    content = (message or {}).get("content") if isinstance(message, dict) else message
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str): parts.append(block)
            elif isinstance(block, dict) and block.get("text"): parts.append(str(block["text"]))
        return "".join(parts).strip() or None
    return None

def _fernet():
    key = os.getenv("LLM_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("LLM_ENCRYPTION_KEY tanımlı değil")
    return Fernet(key.encode())

def encrypt_key(value): return _fernet().encrypt(value.encode()).decode()
def decrypt_key(value): return _fernet().decrypt(value.encode()).decode()

async def list_config():
    return await database.get_llm_config()

async def analyze(snapshot):
    cfg = await database.get_active_llm_config()
    if not cfg: return {"enabled": False, "status": "disabled", "text": None}
    skills = "\n\n".join(s["instructions"] for s in cfg["skills"] if s["enabled"])
    system = PERSONA + "\n" + OUTPUT_RULES + "\nSen kripto scalping teknik analiz uzmanısın. TÜM yanıtlarını yalnızca Türkçe ver. Sadece sağlanan verileri yorumla; eksik likidite değerleri için tahmin uydurma. Emir açma, kapama veya gerçek işlem talimatı verme. Yanıtını piyasa rejimi, kanıtlar, riskler, veri eksikleri ve güven seviyesi başlıklarıyla açıkla. Paper-trading ve fiyat hedefiyle ilgili genel uyarı/not cümlelerini her yanıtta tekrarlama; yalnızca kullanıcı özellikle sorarsa veya somut bir veri sınırlaması analizi doğrudan etkiliyorsa belirt.\n" + skills
    payload = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}]}
    base_url = cfg["provider"]["base_url"].rstrip("/")
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    def call():
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        with urlopen(req, timeout=90) as response: return _decode_provider_response(response.read())
    try:
        result = await asyncio.to_thread(call)
        # Some compatible gateways wrap the upstream response in {success, data}.
        payload_result = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), (dict, list, str)) else result
        if isinstance(payload_result, str):
            try: payload_result = json.loads(payload_result)
            except json.JSONDecodeError: pass
        choices = payload_result.get("choices") if isinstance(payload_result, dict) else None
        text = None
        if choices and isinstance(choices, list):
            first = choices[0] or {}
            message = first.get("message") or {}
            text = _message_text(message) or first.get("text")
        if not text and isinstance(payload_result, dict):
            text = payload_result.get("output_text") or payload_result.get("response") or payload_result.get("content")
        if not text and isinstance(payload_result, str):
            text = payload_result
        if not text:
            provider_error = (payload_result.get("error") if isinstance(payload_result, dict) else None) or (result.get("error") if isinstance(result, dict) else None)
            detail = provider_error.get("message") if isinstance(provider_error, dict) else provider_error
            fields = ', '.join(payload_result.keys()) if isinstance(payload_result, dict) else type(payload_result).__name__
            raise RuntimeError(detail or f"Provider beklenmeyen yanıt döndürdü (alanlar: {fields})")
        return {"enabled": True, "status": "ok", "text": text, "model": cfg["model"]["name"], "generated_at": time.time()}
    except Exception as exc:
        return {"enabled": True, "status": "error", "text": None, "error": str(exc)}

async def embedding(text, model_id=None):
    cfg = await database.get_embedding_llm_config(model_id)
    if not cfg: return {"status": "disabled", "error": "Aktif LLM yapılandırması yok"}
    model = cfg["model"]
    if model.get("model_type", "chat") != "embedding":
        return {"status": "error", "error": "Aktif model embedding modeli değil"}
    payload = {"model": model["name"], "input": text}
    base_url = cfg["provider"]["base_url"].rstrip("/")
    url = base_url if base_url.endswith("/embeddings") else base_url + "/embeddings"
    def call():
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        with urlopen(req, timeout=30) as response: return _decode_provider_response(response.read())
    try:
        result = await asyncio.to_thread(call); data = result.get("data", result) if isinstance(result, dict) else result
        vector = data[0].get("embedding") if isinstance(data, list) and data else None
        if vector is None and isinstance(data, dict): vector = data.get("embedding")
        if not isinstance(vector, list) or not vector: raise RuntimeError("Provider embedding yanıtında vector bulunamadı")
        expected = model.get("dimensions") or 2048
        if expected and len(vector) != int(expected): raise RuntimeError(f"Dimension uyumsuzluğu: beklenen {expected}, gelen {len(vector)}")
        return {"status":"ok", "model":model["name"], "model_id":model.get("id"), "dimensions":len(vector), "vector":vector, "latency_ms":None}
    except Exception as exc:
        return {"status":"error", "error":str(exc), "model":model.get("name")}

async def chat(snapshot, messages, tools=None, tool_executor=None):
    cfg = await database.get_active_llm_config()
    if not cfg: return {"enabled": False, "status": "disabled", "text": None}
    skills = "\n\n".join(s["instructions"] for s in cfg["skills"] if s["enabled"])
    system = PERSONA + "\n" + OUTPUT_RULES + "\nSen Türkçe konuşan bir strateji araştırma asistanısın. TÜM yanıtlarını kesinlikle Türkçe ver. Bu uygulama, PostgreSQL/pgvector üzerinde sohbet, işlem, sinyal, karar ve teknik snapshot kayıtlarını arayabildiğin katmanlı bir sistem hafızasına sahiptir. Bu kişisel veya sınırsız bir hafıza değildir: yalnızca sisteme kaydedilmiş ve araçların döndürdüğü verilere erişebilirsin. İşlem, sinyal, açık pozisyon veya ayar bilgisi gerekiyorsa önce uygun veritabanı/arama aracını çağır; araç çağırmadan veri uydurma. İleri incelemede yalnızca gerektiğinde read_only_sql aracını kullan ve sadece dönen satırlara dayan. Kullanıcı istemedikçe geçmiş verileri çekme. Paper-trading ve fiyat hedefiyle ilgili genel uyarı/not cümlelerini her yanıtta tekrarlama; yalnızca kullanıcı özellikle sorarsa veya somut bir veri sınırlaması analizi doğrudan etkiliyorsa belirt.\n" + skills
    conversation = [{"role": "system", "content": system}, {"role": "user", "content": "Kullanılabilir araçlar ve özet context:\n" + json.dumps(snapshot, ensure_ascii=False, default=str)}]
    for item in (messages or [])[-12:]:
        if not isinstance(item, dict):
            continue
        # Preserve tool-call metadata when the frontend sends a previous
        # assistant/tool exchange. Dropping it makes OpenAI-compatible APIs
        # reject the next request or return an empty answer.
        message = {"role": str(item.get("role", "user")), "content": item.get("content", "")}
        for key in ("tool_calls", "tool_call_id", "name"):
            if key in item: message[key] = item[key]
        conversation.append(message)
    payload = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"], "messages": conversation}
    if tools: payload["tools"] = tools; payload["tool_choice"] = "auto"
    base_url = cfg["provider"]["base_url"].rstrip("/"); url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    def call():
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        with urlopen(req, timeout=45) as response: return _decode_provider_response(response.read())
    async def call_with_retry():
        last_error = None
        for attempt in range(2):
            try:
                return await asyncio.to_thread(call)
            except (TimeoutError, OSError) as exc:
                last_error = exc
                if attempt == 0: await asyncio.sleep(0.4)
        raise RuntimeError(f"LLM gateway yanıt vermedi: {last_error}") from last_error
    def response_data(value):
        """Normalize compatible gateway wrappers and JSON-string data fields."""
        current = value
        for _ in range(3):
            if isinstance(current, str):
                try: current = json.loads(current)
                except json.JSONDecodeError: return current
            if isinstance(current, dict) and isinstance(current.get("data"), (dict, list, str)):
                current = current["data"]
                continue
            return current
        return current
    try:
        result = None
        result = await call_with_retry()
        max_tool_rounds = 6
        for tool_round in range(max_tool_rounds):
            data = response_data(result)
            choices = data.get("choices", []) if isinstance(data, dict) else []
            first = choices[0] if choices else {}
            assistant = first.get("message") or {}
            tool_calls = assistant.get("tool_calls", []) or []
            # A number of OpenAI-compatible gateways still emit the legacy
            # single-call function_call shape. Normalize it to the modern
            # tool_calls protocol before appending the follow-up messages.
            legacy_call = assistant.get("function_call")
            if not tool_calls and isinstance(legacy_call, dict) and legacy_call.get("name"):
                tool_calls = [{
                    "id": f"legacy_call_{tool_round}",
                    "type": "function",
                    "function": legacy_call,
                }]
                assistant = {**assistant, "tool_calls": tool_calls}
            if not tool_calls or not tool_executor: break
            conversation.append(assistant)
            for call_item in tool_calls:
                fn = call_item.get("function") or {}; name = fn.get("name", "")
                try:
                    arguments = _decode_json_value(fn.get("arguments", "{}"), f"{name} araç argümanları")
                    if not isinstance(arguments, dict): raise ValueError("Araç argümanları nesne olmalı")
                    tool_result = await tool_executor(name, arguments)
                except Exception as tool_error:
                    tool_result = {"error": str(tool_error), "tool": name, "retryable": False}
                conversation.append({"role": "tool", "tool_call_id": call_item.get("id", name), "name": name, "content": json.dumps(tool_result, ensure_ascii=False, default=str)})
            payload["messages"] = conversation
            # Every tool round must be followed by a provider call, including
            # the last allowed round. Otherwise the last tool-call object is
            # incorrectly treated as the final assistant answer.
            result = await call_with_retry()
        else:
            raise RuntimeError(f"LLM araç döngüsü {max_tool_rounds} turda tamamlanamadı")
        data = response_data(result)
        if isinstance(data, str): return {"enabled": True, "status": "ok", "text": data}
        choices = data.get("choices", []) if isinstance(data, dict) else []
        text = _message_text(choices[0].get("message") if choices else None) or (data.get("output_text") if isinstance(data, dict) else None)
        if not text: raise RuntimeError("Provider chat yanıtında metin bulunamadı")
        return {"enabled": True, "status": "ok", "text": text, "model": cfg["model"]["name"], "generated_at": time.time()}
    except Exception as exc:
        return {"enabled": True, "status": "error", "text": None, "error": str(exc)}

async def stream_chat(snapshot, messages):
    """Stream provider deltas without buffering or simulating token output.

    The endpoint deliberately has no tool loop: tool calls require a complete
    assistant message and continue through ``chat``. This keeps streamed text
    strictly provider-owned while preserving the existing tool-capable path.
    """
    cfg = await database.get_active_llm_config()
    if not cfg:
        yield {"event": "error", "data": {"status": "disabled", "error": "Aktif LLM yapılandırması yok"}}
        return
    skills = "\n\n".join(s["instructions"] for s in cfg["skills"] if s["enabled"])
    system = PERSONA + "\n" + OUTPUT_RULES + "\nSen Türkçe konuşan bir strateji araştırma asistanısın. Yalnızca sağlanan public market verisini yorumla; gerçek emir veya işlem talimatı verme.\n" + skills
    conversation = [{"role": "system", "content": system}, {"role": "user", "content": "Güncel snapshot:\n" + json.dumps(snapshot, ensure_ascii=False, default=str)}]
    for item in (messages or [])[-12:]:
        if isinstance(item, dict):
            conversation.append({k: item[k] for k in ("role", "content") if k in item})
    payload = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"], "messages": conversation, "stream": True}
    base_url = cfg["provider"]["base_url"].rstrip("/")
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    try:
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}
        import queue
        lines = queue.Queue()
        def read_stream():
            try:
                request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
                with urlopen(request, timeout=120) as response:
                    if response.status >= 400:
                        lines.put(("error", f"Provider HTTP {response.status}: {response.read(1000).decode(errors='replace')}"))
                    else:
                        for raw_line in response:
                            lines.put(("line", raw_line.decode("utf-8", errors="replace")))
            except Exception as exc:
                lines.put(("error", str(exc)))
            finally:
                lines.put(("done", None))
        reader = asyncio.create_task(asyncio.to_thread(read_stream))
        emitted = False
        while True:
            kind, raw_line = await asyncio.to_thread(lines.get)
            if kind == "error":
                raise RuntimeError(raw_line)
            if kind == "done":
                break
            line = raw_line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                break
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = item.get("data", item) if isinstance(item, dict) else item
            choices = data.get("choices", []) if isinstance(data, dict) else []
            delta = choices[0].get("delta", {}) if choices else {}
            text = _message_text(delta) or (choices[0].get("text") if choices else None)
            if text:
                emitted = True
                yield {"event": "delta", "data": {"text": text}}
        await reader
        yield {"event": "done", "data": {"status": "ok", "model": cfg["model"]["name"], "generated_at": time.time(), "provider_stream": True, "emitted": emitted}}
    except Exception as exc:
        yield {"event": "error", "data": {"status": "error", "error": str(exc)}}
