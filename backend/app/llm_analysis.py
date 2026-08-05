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
    system = "You are a crypto scalping technical analyst. Explain only the supplied data. Never invent missing liquidity values. Do not place orders or give execution commands.\n" + skills
    payload = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}]}
    base_url = cfg["provider"]["base_url"].rstrip("/")
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    def call():
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        with urlopen(req, timeout=90) as response: return json.loads(response.read().decode())
    try:
        result = await asyncio.to_thread(call)
        choices = result.get("choices") if isinstance(result, dict) else None
        text = None
        if choices and isinstance(choices, list):
            first = choices[0] or {}
            message = first.get("message") or {}
            text = message.get("content") or first.get("text")
        if not text and isinstance(result, dict):
            text = result.get("output_text") or result.get("response") or result.get("content")
        if not text:
            provider_error = result.get("error") if isinstance(result, dict) else None
            detail = provider_error.get("message") if isinstance(provider_error, dict) else provider_error
            raise RuntimeError(detail or f"Provider beklenmeyen yanıt döndürdü (alanlar: {', '.join(result.keys()) if isinstance(result, dict) else type(result).__name__})")
        return {"enabled": True, "status": "ok", "text": text, "model": cfg["model"]["name"], "generated_at": time.time()}
    except Exception as exc:
        return {"enabled": True, "status": "error", "text": None, "error": str(exc)}
