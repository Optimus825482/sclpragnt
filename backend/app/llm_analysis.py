import asyncio, ast, json, os, re, time
from urllib.error import HTTPError
from urllib.request import Request
from cryptography.fernet import Fernet
from app import database
from app.security import safe_provider_open, validate_provider_url

# Sentinel returned by _json_load_lenient when no recovery strategy works;
# a real ``None`` payload is distinguishable from "undecodable".
_JSON_UNDECODABLE = object()

PERSONA = """Persona adın Scalper. Kullanıcının adı Erkan'dır; ona Türkçe, doğrudan ve teknik bir çalışma arkadaşı gibi hitap edersin. Erkan'ın talimatlarını mevcut sistem kapsamı içinde uygularsın; kimlik, yetki veya kişisel bilgi uydurmazsın. Paper-trading güvenlik kurallarını aşmayı önermezsin."""
TRADE_MANAGER_RULES = """SCALPER TRADE MANAGER ZORUNLU KURALLARI:
- Yalnızca paper trading yap; gerçek emir aracı çağırma. Bu güvenlik sınırını kullanıcıya her yanıtta tekrar etme.
- Girişte kapanmış mumları ve `market_scan.strategy_contract` içindeki aktif strateji koşullarını kullan; sözleşmede olmayan teyitleri zorunlu yapma.
- Orderflow, likidite, ATR kapasitesi ve round-trip maliyeti uygun değilse ENTRY_INELIGIBLE kabul et; bu bir sinyal veya işlem değildir.
- Aktif strateji mean-reversion ise yalnızca sözleşmedeki BB/MFI koşullarını değerlendir; genel aşırı alım veya trend yorumunu ek BUY filtresine dönüştürme.
- Sembolün net PnL, expectancy ve loss streak geçmişini giriş kararına dahil et.
- LLM pozisyonu kapattıktan sonra cooldown ve sembolün dinamik re-arm hareketi tamamlanmadan aynı sembole dönme.
- BUY_BLOCKED işlem değildir; yalnızca gerçek BUY_SIGNAL pozisyon açılışıdır.
- Öğrenme tek işlemle kural değiştirmez; yeterli örnek ve kronolojik OOS doğrulaması olmadan yeni kuralı etkinleştirme.
"""
OUTPUT_RULES = """ÇIKTI BİÇİMİ KURALLARI:
- Kompakt ve bilgi-yoğun yanıt ver: dolgu cümlesi, giriş paragrafı, özet-özeti, "aşağıda inceleyeceğim" gibi yapılar YOK.
- Kullanıcı açıkça istemedikçe gösterge değerlerini tek tek sıralayıp teknik detay dökümü yapma (RSI şu, MACD şu, EMA şu, ADX şu...). Gösterge/kanıt adları yalnızca sonucu destekleyen tek bir cümle içinde geçebilir; asla amaç değil, gerekçedir.
- Analiz isteyen kullanıcının derdi "şu an ne oluyor, bundan sonra ne olabilir, kısaca neden"dir. Yanıtı kompakt ama gerekçeli kur: (1) Şu anki durum, (2) bundan sonrası için net senaryolar (olası yön + tetikleyici seviye + bozulma seviyesi), (3) bu görüşün tek kanıt cümlesi (neden), (4) tek cümlelik sonuç. Toplamda kısa tut; gerekmedikçe başlık/yığın açma ama gerekçeyi de esirgeme.
- Başlıkları (`###`) yalnızca gerçekten çok bölümlü uzun yanıtlarda kullan; kısa yanıtta doğrudan yaz. Her başlık altını kalınlaştırarak tekrarlama.
- Kalın (**metin**) yalnızca gerçekten kritik sayı/seviyeler için; her cümleyi veya her maddeyi kalınlaştırma.
- Madde listelerinde her madde tek satır kalsın; madde içine alt madde açma.
- Aynı bilgiyi hem metinde hem tabloda hem maddede tekrar etme; bir kez söyle.
- Kapanış cümlesi, özet tekrarı, "istersen ... da inceleyebilirim" türü dolgu yok; son veri/nokta ile bitir.
- Türkçe kelimeler arasındaki boşlukları mutlaka koru; kelimeleri veya cümleleri birleştirme.
- Yanıtı okunabilir Markdown olarak yaz: ana bölümler için `### Başlık`, maddeler için `- madde` kullan.
- Her cümle arasında normal boşluk bırak; sembol, sayı, yüzde ve birim değerlerini ayırarak yaz (ör. `8.97 TRY`, `%0.25`).
- Ham JSON, HTML veya tek satır sıkıştırılmış metin üretme.
- `BUY_BLOCKED`, `ENTRY_INELIGIBLE` veya `entry_ineligible:*` bir işlem açıldığı anlamına gelmez; bunu daima "işlem açılmadı" olarak raporla.
- Bir aday risk/likidite nedeniyle engellenirse onu başarılı işlem sayma; mevcut aday listesinden başka sembol araştır ve yalnızca `BUY_SIGNAL` varsa açılmış işlem de.
- `market_scan` verildiğinde tüm taranan sembolleri karşılaştır; yükseliş ve yüksek skor adaylarını çoklu timeframe kanıtlarıyla derinleştir.
- `market_scan.strategy_contract` verildiğinde aktif stratejinin sözleşmesi tek sinyal otoritesidir. Sözleşmede `ignored_for_signal_decision` olarak belirtilen RSI/MTF/momentum/CMO/CRSI gibi alanları BUY veya NO_SIGNAL filtresi yapma; yalnızca bağlamsal bilgi olarak yaz.
- `price_action` alanını yalnızca teyitli kapanmış mum setup'ı olarak yorumla: pin bar, inside bar ve fakey tek başına işlem sinyali değildir.
- Price-action setup'ını trend/rejim, destek-direnç veya breakout seviyesi, hacim, orderflow/derinlik, ATR kapasitesi ve maliyet sonrası risk/ödül ile birlikte değerlendir.
- Aşırı alımda, Bollinger üstünde veya negatif orderflow varken yeni long açma; backend giriş kapısı bu koşulları zorunlu olarak reddeder.
- LLM pozisyonu kapattığında aynı sembolü hemen yeniden alma; yeni trend/pullback veya kapanış teyitli breakout oluşmasını bekle.
- Açık mumdan sinyal üretme; teyit kapanışını bekle. Chop/range ortasında ve "no man's land" bölgelerinde setup skorunu düşür veya `watch/avoid` de.
- Kırılımı kapanış teyidi olmadan onaylama; false-break/fakey ile gerçek breakout'u ayır ve belirsizliği açıkça belirt.
- Kullanıcı işlem fikri istediğinde giriş bölgesi, teyit, invalidasyon/stop, hedef, risk ve güven seviyesini doğrudan ver.
- Kullanıcı özellikle istemedikçe "yatırım tavsiyesi değildir", "garanti verilemez", "her öneriyi uygulamayın" gibi tekrarlayan sorumluluk uyarıları ekleme. Belirsizliği ayrı bir uyarı cümlesiyle değil, senaryo olasılığı, karşı kanıt ve invalidasyon seviyesiyle göster.
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

def _provider_http_error(error: HTTPError):
    """Keep the upstream error body; compatible gateways often explain 5xx here."""
    try:
        raw = error.read(2000).decode("utf-8-sig", errors="replace")
        detail = _decode_provider_response(raw)
        if isinstance(detail, dict):
            detail = detail.get("error", detail.get("message", detail))
            if isinstance(detail, dict): detail = detail.get("message", detail)
        return f"Provider HTTP {error.code}: {detail}"
    except Exception:
        return f"Provider HTTP {error.code}: {error.reason}"

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


def _brace_scan(text: str):
    """Return the largest balanced top-level object substring, or None.

    Models often wrap JSON in prose (``İşte analiz: {...} Umarım yardımcı
    olur``) or omit the final closing brace.  A naive ``find("{")..rfind("}")``
    breaks whenever a scenario string contains a ``}``.  This scanner walks
    string literals (escape-aware) and only accepts a substring whose braces
    balance at depth zero.
    """
    start = None
    depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("\"", "'"):
            quote = char
        elif char == "{":
            if start is None:
                start = index
            depth += 1
        elif char == "}":
            if start is not None:
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
    if start is not None and depth > 0:
        # Unterminated top-level object (model cut off mid-write).
        return text[start:]
    return None


def _repair_scalar_tokens(text: str) -> str:
    """Convert single-quoted JSON scalars to double-quoted equivalents.

    The ast.literal_eval path already handles whole ``'...'`` documents; this
    covers the JSON-specific syntax repair: single-quoted string *scalars*
    nested in an otherwise double-quoted document, plus bare ``None`` /
    ``True`` / ``False`` constants.  Double-quoted spans are left untouched
    because they are already valid JSON.
    """
    single = re.compile(r"'((?:\\.|[^'\\])*)'")
    def _fix(match):
        body = match.group(1).replace("\\'", "'").replace("\\\\", "\\")
        return json.dumps(body)
    text = single.sub(_fix, text)
    text = re.sub(r"\bNone\b", "null", text)
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    return text


def _json_load_lenient(value, *, _visited: int = 0) -> object:
    """Best-effort decode of model JSON that is not strictly valid.

    Attempt order: full text, balanced-brace slice, outer fence removal,
    double-encoded JSON (``\"{...}\"``), then syntax repair that re-quotes
    barewords/keys, converts single quotes, and drops trailing commas before
    one final ``json.loads``.  Returns a sentinel ``_JSON_UNDECODABLE`` when
    nothing works so callers can keep a ``None`` result meaningful.
    """
    if _visited > 5 or value is None:
        return _JSON_UNDECODABLE
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return _JSON_UNDECODABLE
    # Strip markdown fences first so the brace scan sees the payload.
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[A-Za-z]*\s*", "", candidate).strip()
        candidate = re.sub(r"\s*```\s*$", "", candidate).strip()
    span = _brace_scan(candidate)
    pieces = [candidate, span] if span else [candidate]
    for piece in pieces:
        if not piece:
            continue
        # A provider JSON-string content field returns a quoted string that
        # decodes to valid JSON text (e.g. '"{\\"summary\\":...}"').  The
        # string itself is not the payload: peel the outer quotes and retry.
        if piece.startswith('"') and piece.endswith('"'):
            try:
                inner = json.loads(piece)
                if isinstance(inner, str) and not inner.startswith("```"):
                    recovered = _json_load_lenient(inner, _visited=_visited + 1)
                    if recovered is not _JSON_UNDECODABLE:
                        return recovered
            except json.JSONDecodeError:
                pass
        if piece.startswith("{") or piece.startswith("["):
            # Unterminated top-level object (model cut off mid-write): the
            # decoder may still succeed with a single closing brace appended
            # (a dangling comma before the cut is dropped first).  Even when
            # the tail already closes an inner list/object, the top-level
            # container may still be open, so always try the appended close.
            tail = piece.rstrip()
            if tail.endswith(","):
                tail = tail[:-1]
            try:
                return _decode_provider_response(tail)
            except Exception:
                pass
            try:
                return _decode_provider_response(tail + ("}" if piece.startswith("{") else "]"))
            except Exception:
                pass
        # Single-quoted JSON: ast.literal_eval handles dicts whose keys and
        # string scalars use '...' (JSON itself only permits double quotes).
        if re.search(r"['\"]", piece):
            try:
                return ast.literal_eval(piece)
            except (SyntaxError, ValueError):
                pass
    # Syntax repair: unquote bare keys, convert None/True/False, single
    # quotes, drop trailing commas.  Applied to the brace slice when present
    # so trailing prose does not poison the attempt.
    target = span or candidate
    repaired = _repair_scalar_tokens(re.sub(r"([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', target))
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    try:
        return _decode_provider_response(repaired)
    except Exception:
        return _JSON_UNDECODABLE


def _context_window_messages(messages, token_budget=900_000):
    """Keep the newest conversation messages inside the 1M-token model window.

    The frontend persists the complete session. The provider request keeps the
    newest messages up to a conservative budget so system/context instructions
    and the model response still have headroom.
    """
    selected = []
    used = 0
    for item in reversed([message for message in (messages or []) if isinstance(message, dict)]):
        content = str(item.get("content") or "")
        estimated = max(1, (len(content) + 24) // 4)
        if selected and used + estimated > token_budget:
            break
        selected.append(item)
        used += estimated
    return list(reversed(selected)), used


# Tool-loop cost guardrails: each round resends the whole conversation, so an
# agent that keeps calling tools burns tokens quadratically. Env-tunable.
TOOL_LOOP_MAX_ROUNDS = max(1, int(os.getenv("LLM_TOOL_MAX_ROUNDS", "25")))
TOOL_LOOP_TOKEN_BUDGET = max(50_000, int(os.getenv("LLM_TOOL_TOKEN_BUDGET", "600_000")))
TOOL_RESULT_MAX_CHARS = max(2_000, int(os.getenv("LLM_TOOL_RESULT_MAX_CHARS", "40_000")))


def _estimate_tokens(conversation):
    total = 0
    for message in conversation:
        if isinstance(message, dict):
            total += max(1, (len(str(message.get("content") or "")) + 24) // 4)
    return total


def _trim_tool_result(value):
    """Bound a single tool payload so one huge read cannot blow the budget."""
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    limit = TOOL_RESULT_MAX_CHARS
    if len(text) <= limit:
        return value if not isinstance(value, str) else text
    return {"truncated": True, "original_chars": len(text), "preview": text[:limit]}

def _fernet():
    key = os.getenv("LLM_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("LLM_ENCRYPTION_KEY tanımlı değil")
    return Fernet(key.encode())

def encrypt_key(value): return _fernet().encrypt(value.encode()).decode()
def decrypt_key(value): return _fernet().decrypt(value.encode()).decode()

async def list_config():
    return await database.get_llm_config()

async def analyze(snapshot, max_tokens=None):
    cfg = await database.get_active_llm_config()
    if not cfg: return {"enabled": False, "status": "disabled", "text": None}
    skills = "\n\n".join(s["instructions"] for s in cfg["skills"] if s["enabled"])
    system = PERSONA + "\n" + TRADE_MANAGER_RULES + "\n" + OUTPUT_RULES + "\nSen kripto scalping teknik analiz uzmanısın. TÜM yanıtlarını yalnızca Türkçe ver. Sadece sağlanan verileri yorumla; eksik likidite değerleri için tahmin uydurma. Emir açma, kapama veya gerçek işlem talimatı verme. Kullanıcı bir coin için analiz istediğinde kompakt ama gerekçeli yanıt ver: önce net durumu, sonra olası senaryoları (yön + tetikleyici seviye + bozulma seviyesi), sonra bu görüşün tek neden cümlesini, en sonda tek cümlelik sonucu söyle. Gösterge değerlerini istenmedikçe tek tek sıralama; tek kanıt cümlesi yeterli. Paper-trading ve fiyat hedefiyle ilgili genel uyarı/not cümlelerini her yanıtta tekrarlama; yalnızca kullanıcı özellikle sorarsa veya somut bir veri sınırlaması analizi doğrudan etkiliyorsa belirt.\n" + skills
    base_url = await validate_provider_url(cfg["provider"]["base_url"])
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    async def call(max_tokens):
        payload = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False, default=str)}]}
        if max_tokens: payload["max_tokens"] = int(max_tokens)
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        response = await safe_provider_open(req, timeout=90)
        return _decode_provider_response(response.read())
    def _unwrap(result):
        # Some compatible gateways wrap the upstream response in {success, data}.
        payload_result = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), (dict, list, str)) else result
        if isinstance(payload_result, str):
            try: payload_result = json.loads(payload_result)
            except json.JSONDecodeError: pass
        return payload_result
    def _extract_text(payload_result):
        choices = payload_result.get("choices") if isinstance(payload_result, dict) else None
        text = None
        finish_reason = None
        if choices and isinstance(choices, list):
            first = choices[0] or {}
            message = first.get("message") or {}
            finish_reason = first.get("finish_reason")
            text = _message_text(message) or first.get("text")
        if not text and isinstance(payload_result, dict):
            text = payload_result.get("output_text") or payload_result.get("response") or payload_result.get("content")
        if not text and isinstance(payload_result, str):
            text = payload_result
        return text, finish_reason
    try:
        result = await call(max_tokens)
        payload_result = _unwrap(result)
        text, finish_reason = _extract_text(payload_result)
        # Reasoning modeller gizli akıl yürütmeye cap'i harcayıp içerik yazamayabilir; cap'siz tek tekrar.
        if not text and finish_reason == "length" and max_tokens:
            result = await call(None)
            payload_result = _unwrap(result)
            text, finish_reason = _extract_text(payload_result)
        if not text:
            provider_error = (payload_result.get("error") if isinstance(payload_result, dict) else None) or (result.get("error") if isinstance(result, dict) else None)
            detail = provider_error.get("message") if isinstance(provider_error, dict) else provider_error
            fields = ', '.join(payload_result.keys()) if isinstance(payload_result, dict) else type(payload_result).__name__
            raise RuntimeError(detail or f"Provider metin döndürmedi (alanlar: {fields}, finish_reason: {finish_reason})")
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
    base_url = validate_provider_url(cfg["provider"]["base_url"])
    url = base_url if base_url.endswith("/embeddings") else base_url + "/embeddings"
    async def call():
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        response = await safe_provider_open(req, timeout=30)
        return _decode_provider_response(response.read())
    try:
        result = await call(); data = result.get("data", result) if isinstance(result, dict) else result
        vector = data[0].get("embedding") if isinstance(data, list) and data else None
        if vector is None and isinstance(data, dict): vector = data.get("embedding")
        if not isinstance(vector, list) or not vector: raise RuntimeError("Provider embedding yanıtında vector bulunamadı")
        expected = model.get("dimensions") or 2048
        if expected and len(vector) != int(expected): raise RuntimeError(f"Dimension uyumsuzluğu: beklenen {expected}, gelen {len(vector)}")
        return {"status":"ok", "model":model["name"], "model_id":model.get("id"), "dimensions":len(vector), "vector":vector, "latency_ms":None}
    except Exception as exc:
        return {"status":"error", "error":str(exc), "model":model.get("name")}

async def chat(snapshot, messages, tools=None, tool_executor=None, active_skills=None, *, json_mode=False):
    cfg = await database.get_active_llm_config()
    if not cfg: return {"enabled": False, "status": "disabled", "text": None}
    selected = set(str(value) for value in (active_skills or []))
    skills = "\n\n".join(s["instructions"] for s in cfg["skills"] if s["enabled"] and (not selected or str(s["id"]) in selected or s["name"] in selected))
    system = PERSONA + "\n" + TRADE_MANAGER_RULES + "\n" + OUTPUT_RULES + "\nSen Türkçe konuşan bir strateji araştırma asistanısın. TÜM yanıtlarını kesinlikle Türkçe ver. Bu uygulama, PostgreSQL/pgvector üzerinde sohbet, işlem, sinyal, karar ve teknik snapshot kayıtlarını arayabildiğin katmanlı bir sistem hafızasına sahiptir. Bu kişisel veya sınırsız bir hafıza değildir: yalnızca sisteme kaydedilmiş ve araçların döndürdüğü verilere erişebilirsin. İşlem, sinyal, açık pozisyon veya ayar bilgisi gerekiyorsa önce uygun veritabanı/arama aracını çağır; araç çağırmadan veri uydurma. İleri incelemede yalnızca gerektiğinde read_only_sql aracını kullan ve sadece dönen satırlara dayan. Kullanıcı istemedikçe geçmiş verileri çekme. Kullanıcı bir coin için analiz istediğinde gösterge değerlerini tek tek sıralayıp onu boğma ama gerekçesiz de bırakma: kompakt bir analiz yaz — 'şu an ne oluyor', 'bundan sonra ne olabilir' (yön + seviye + bozulma), 'kısaca neden' ve tek cümlelik sonuç. Paper-trading ve fiyat hedefiyle ilgili genel uyarı/not cümlelerini her yanıtta tekrarlama; yalnızca kullanıcı özellikle sorarsa veya somut bir veri sınırlaması analizi doğrudan etkiliyorsa belirt.\n" + skills
    conversation = [{"role": "system", "content": system}, {"role": "user", "content": "Kullanılabilir araçlar ve özet context:\n" + json.dumps(snapshot, ensure_ascii=False, default=str)}]
    context_messages, _estimated_tokens = _context_window_messages(messages)
    for item in context_messages:
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
    if json_mode:
        # Structured-output call. OpenAI-compatible gateways (and the JSON
        # mode behind them) return the object inside content; the response is
        # then re-decoded by the caller. Some self-hosted gateways reject the
        # response_format key, so fall back to a plain call when refused.
        payload["response_format"] = {"type": "json_object"}
        payload.setdefault("temperature", 0.2)
    base_url = await validate_provider_url(cfg["provider"]["base_url"]); url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    async def call():
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}, method="POST")
        response = await safe_provider_open(req, timeout=45)
        return _decode_provider_response(response.read())
    async def call_with_retry():
        last_error = None
        for attempt in range(2):
            try:
                return await call()
            except HTTPError:
                # Provider-level rejections (4xx/5xx) are surfaced to the
                # caller, not retried as transport noise: the fallback path
                # above decides whether to drop response_format.
                raise
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
        try:
            result = await call_with_retry()
        except HTTPError as http_error:
            # Gateways that do not implement response_format commonly answer
            # with 4xx. Retry once without the key so a refused structured
            # call still yields the model text (parsing stays tolerant).
            if json_mode and http_error.code // 100 == 4:
                payload.pop("response_format", None)
                if payload.get("temperature") == 0.2:
                    payload["temperature"] = cfg["model"]["temperature"]
                try:
                    result = await call_with_retry()
                except Exception as exc:
                    raise RuntimeError(f"LLM gateway yanıt vermedi: {exc}") from exc
            else:
                raise
        tool_round = 0
        tool_stats = {"rounds": 0, "tool_calls": 0, "estimated_tokens": 0}
        # while True yerine bounded loop — ölü else clause kaldırıldı
        while tool_round <= TOOL_LOOP_MAX_ROUNDS:
            tool_round += 1
            estimated_tokens = _estimate_tokens(conversation)
            if estimated_tokens > TOOL_LOOP_TOKEN_BUDGET:
                raise RuntimeError(
                    f"LLM araç döngüsü token bütçesini aştı: ~{estimated_tokens} > {TOOL_LOOP_TOKEN_BUDGET}")
            data = response_data(result)
            choices = data.get("choices", []) if isinstance(data, dict) else []
            first = choices[0] if choices else {}
            assistant = first.get("message") or {}
            usage = data.get("usage") or {} if isinstance(data, dict) else {}
            if isinstance(usage, dict) and (usage.get("total_tokens") or usage.get("prompt_tokens")):
                tool_stats["provider_total_tokens"] = int(usage.get("total_tokens") or 0)
                tool_stats["provider_prompt_tokens"] = int(usage.get("prompt_tokens") or 0)
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
            if not tool_calls or not tool_executor:
                break
            conversation.append(assistant)
            for call_item in tool_calls:
                fn = call_item.get("function") or {}; name = fn.get("name", "")
                tool_stats["tool_calls"] += 1
                try:
                    arguments = _decode_json_value(fn.get("arguments", "{}"), f"{name} araç argümanları")
                    if not isinstance(arguments, dict): raise ValueError("Araç argümanları nesne olmalı")
                    tool_result = await tool_executor(name, arguments)
                except Exception as tool_error:
                    tool_result = {"error": str(tool_error), "tool": name, "retryable": False}
                conversation.append({"role": "tool", "tool_call_id": call_item.get("id", name), "name": name,
                                     "content": json.dumps(_trim_tool_result(tool_result), ensure_ascii=False, default=str)})
            payload["messages"] = conversation
            # Every tool round must be followed by a provider call, including
            # the last allowed round. Otherwise the last tool-call object is
            # incorrectly treated as the final assistant answer.
            result = await call_with_retry()
            tool_stats["rounds"] = tool_round
        else:
            # Loop break olmadan bütünce round'ı doldurdu — provider hatası
            raise RuntimeError(f"LLM araç döngüsü {TOOL_LOOP_MAX_ROUNDS} round'da kesildi (olası provider hatası)")
        data = response_data(result)
        if isinstance(data, str): return {"enabled": True, "status": "ok", "text": data, "tool_loop": {**tool_stats, "estimated_tokens": _estimate_tokens(conversation)}}
        choices = data.get("choices", []) if isinstance(data, dict) else []
        text = _message_text(choices[0].get("message") if choices else None) or (data.get("output_text") if isinstance(data, dict) else None)
        if not text: raise RuntimeError("Provider chat yanıtında metin bulunamadı")
        tool_stats["estimated_tokens"] = _estimate_tokens(conversation)
        return {"enabled": True, "status": "ok", "text": text, "model": cfg["model"]["name"],
                "generated_at": time.time(), "tool_loop": tool_stats}
    except Exception as exc:
        return {"enabled": True, "status": "error", "text": None, "error": str(exc)}

async def stream_chat(snapshot, messages, tools=None, tool_executor=None, active_skills=None):
    """SSE-compatible chat path with the same tool loop as buffered chat.

    Providers differ in streaming tool-call support. When tools are supplied,
    execute the canonical tool loop first and expose its lifecycle as SSE;
    this prevents streaming mode from silently losing agent capabilities.
    """
    if tools and tool_executor:
        result = await chat(snapshot, messages, tools, tool_executor, active_skills)
        if result.get("text"):
            yield {"event": "delta", "data": {"text": result["text"]}}
        yield {"event": "done", "data": {**result, "provider_stream": False, "tool_loop": True}}
        return
    cfg = await database.get_active_llm_config()
    if not cfg:
        yield {"event": "error", "data": {"status": "disabled", "error": "Aktif LLM yapılandırması yok"}}
        return
    skills = "\n\n".join(s["instructions"] for s in cfg["skills"] if s["enabled"])
    system = PERSONA + "\n" + TRADE_MANAGER_RULES + "\n" + OUTPUT_RULES + "\nSen Türkçe konuşan bir strateji araştırma asistanısın. Yalnızca sağlanan public market verisini yorumla; gerçek emir veya işlem talimatı verme. Coin analizinde kullanıcıyı gösterge detayıyla boğma ama gerekçesiz bırakma: önce durumu, sonra olası senaryoları (yön + seviye + bozulma), sonra tek neden cümlesi, en sonda net sonucu söyle.\n" + skills
    conversation = [{"role": "system", "content": system}, {"role": "user", "content": "Güncel snapshot:\n" + json.dumps(snapshot, ensure_ascii=False, default=str)}]
    for item in (messages or [])[-12:]:
        if isinstance(item, dict):
            conversation.append({k: item[k] for k in ("role", "content") if k in item})
    payload = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"], "messages": conversation, "stream": True}
    base_url = await validate_provider_url(cfg["provider"]["base_url"])
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    try:
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}
        import queue
        lines = queue.Queue()
        async def read_stream():
            try:
                request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
                response = await safe_provider_open(request, timeout=120)
                if response.status >= 400:
                    lines.put(("error", f"Provider HTTP {response.status}: {response.read(1000).decode(errors='replace')}"))
                else:
                    for raw_line in response:
                        lines.put(("line", raw_line.decode("utf-8", errors="replace")))
            except HTTPError as exc:
                lines.put(("error", _provider_http_error(exc)))
            except Exception as exc:
                lines.put(("error", str(exc)))
            finally:
                lines.put(("done", None))
        reader = asyncio.create_task(read_stream())
        emitted = False
        while True:
            # Blocking queue.get yerine asyncio.Queue kullan — event loop'u bloke etme
            try:
                kind, raw_line = await asyncio.wait_for(asyncio.to_thread(lines.get), timeout=1.0)
            except asyncio.TimeoutError:
                continue
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
