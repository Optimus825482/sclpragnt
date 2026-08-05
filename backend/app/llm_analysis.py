import asyncio, base64, json, os, time
from urllib.request import Request, urlopen
from cryptography.fernet import Fernet
from app import database

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
    system = "Sen kripto scalping teknik analiz uzmanısın. TÜM yanıtlarını yalnızca Türkçe ver. Sadece sağlanan verileri yorumla; eksik likidite değerleri için tahmin uydurma. Emir açma, kapama veya gerçek işlem talimatı verme. Yanıtını piyasa rejimi, kanıtlar, riskler, veri eksikleri ve güven seviyesi başlıklarıyla açıkla. Bu sistem paper trading kullanır.\n" + skills
    payload = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}]}
    base_url = cfg["provider"]["base_url"].rstrip("/")
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    def call():
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        with urlopen(req, timeout=90) as response: return json.loads(response.read().decode())
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
            text = message.get("content") or first.get("text")
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

async def chat(snapshot, messages, tools=None, tool_executor=None):
    cfg = await database.get_active_llm_config()
    if not cfg: return {"enabled": False, "status": "disabled", "text": None}
    skills = "\n\n".join(s["instructions"] for s in cfg["skills"] if s["enabled"])
    system = "Sen Türkçe konuşan bir strateji araştırma asistanısın. TÜM yanıtlarını kesinlikle Türkçe ver. İşlem, sinyal veya ayar bilgisi gerekiyorsa mevcut araçlardan uygun olanı çağır; araç çağırmadan veri uydurma. Kullanıcı istemedikçe geçmiş verileri çekme. Gerçek emir veya yatırım talimatı verme; bu sistem paper trading kullanır.\n" + skills
    conversation = [{"role": "system", "content": system}, {"role": "user", "content": "Kullanılabilir araçlar ve özet context:\n" + json.dumps(snapshot, ensure_ascii=False)}]
    conversation.extend([{"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in (messages or [])[-12:]])
    payload = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"], "messages": conversation}
    if tools: payload["tools"] = tools; payload["tool_choice"] = "auto"
    base_url = cfg["provider"]["base_url"].rstrip("/"); url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    def call():
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        with urlopen(req, timeout=90) as response: return json.loads(response.read().decode())
    try:
        for _ in range(3):
            result = await asyncio.to_thread(call); data = result.get("data", result) if isinstance(result, dict) else result
            choices = data.get("choices", []) if isinstance(data, dict) else []
            first = choices[0] if choices else {}
            tool_calls = (first.get("message") or {}).get("tool_calls", [])
            if not tool_calls or not tool_executor: break
            conversation.append(first.get("message") or {})
            for call_item in tool_calls:
                fn = call_item.get("function") or {}; name = fn.get("name", "")
                try: arguments = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError: arguments = {}
                tool_result = await tool_executor(name, arguments)
                conversation.append({"role": "tool", "tool_call_id": call_item.get("id", name), "name": name, "content": json.dumps(tool_result, ensure_ascii=False)})
            payload["messages"] = conversation
        data = result.get("data", result) if isinstance(result, dict) else result
        if isinstance(data, str):
            try: data = json.loads(data)
            except json.JSONDecodeError: return {"enabled": True, "status": "ok", "text": data}
        choices = data.get("choices", []) if isinstance(data, dict) else []
        text = ((choices[0].get("message") or {}).get("content") if choices else None) or (data.get("output_text") if isinstance(data, dict) else None)
        if not text: raise RuntimeError("Provider chat yanıtında metin bulunamadı")
        return {"enabled": True, "status": "ok", "text": text, "model": cfg["model"]["name"], "generated_at": time.time()}
    except Exception as exc:
        return {"enabled": True, "status": "error", "text": None, "error": str(exc)}
