import re, time

with open(r'D:\scalperagent_v4\backend\app\routers\velocity.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the placeholder I just wrote if it's a small file
if len(content) < 100:
    with open(r'D:\scalperagent_v4\backend\app\routers\velocity.py', 'r', encoding='utf-8') as f:
        content = f.read()

old = 'VELOCITY_CALIBRATED_HIT_PCT = 19.3\n\n\ndef _velocity_rsi(closes, n=14):'
new = '''VELOCITY_CALIBRATED_HIT_PCT = 19.3

# Binance TR rate limiter: token bucket, ~8 req/s max (conservative).
# Her scan_one / fetch_klines / top_gainers / ticker_24h cagrisi bu
# limiter uzerinden gecer. 2026-09-07.
_VELOCITY_RATE_LIMIT_RPS = 8.0
_VELOCITY_RATE_BURST = 12
_velocity_rate_tokens = _VELOCITY_RATE_BURST
_velocity_rate_last_refill = time.time()
_velocity_rate_lock = asyncio.Lock()

async def _velocity_rate_acquire():
    """Token bucket rate limiter: burst kadar token kuyruga, saniyede RPS oraninda yenilenir."""
    global _velocity_rate_tokens, _velocity_rate_last_refill
    async with _velocity_rate_lock:
        now = time.time()
        elapsed = now - _velocity_rate_last_refill
        _velocity_rate_tokens = min(_VELOCITY_RATE_BURST, _velocity_rate_tokens + elapsed * _VELOCITY_RATE_LIMIT_RPS)
        _velocity_rate_last_refill = now
        if _velocity_rate_tokens >= 1.0:
            _velocity_rate_tokens -= 1.0
            return True
        wait = (1.0 - _velocity_rate_tokens) / _VELOCITY_RATE_LIMIT_RPS
        await asyncio.sleep(wait + 0.05)
        _velocity_rate_tokens = 0
        return True

def _rate_limit_stats():
    """Anlik rate limit durumu (diagnostics icin)."""
    return {'tokens_remaining': round(_velocity_rate_tokens, 1),
            'burst': _VELOCITY_RATE_BURST,
            'rps': _VELOCITY_RATE_LIMIT_RPS}


def _velocity_rsi(closes, n=14):'''

content = content.replace(old, new, 1)
assert content.count('_velocity_rate_acquire') >= 1, 'rate limiter not inserted'

# Wrap klines calls in scan_one with rate acquire
old_scan_call = "rows = await fetch_klines(symbol, \"1m\", 60)"
new_scan_call = "await _velocity_rate_acquire()\n                rows = await fetch_klines(symbol, \"1m\", 60)"
content = content.replace(old_scan_call, new_scan_call, 1)

# Wrap m5_rows in scan_one (second fetch_klines inside scan_one)
old_m5_call = "m5_rows = await fetch_klines(symbol, \"5m\", 40)  # ~3.3 saat warmup"
new_m5_call = "await _velocity_rate_acquire()\n                m5_rows = await fetch_klines(symbol, \"5m\", 40)  # ~3.3 saat warmup"
content = content.replace(old_m5_call, new_m5_call, 1)

# Wrap top_gainers call
old_tg = "gainer_rows = await top_gainers(config.VELOCITY_POOL_SIZE)"
new_tg = "await _velocity_rate_acquire()\n        gainer_rows = await top_gainers(config.VELOCITY_POOL_SIZE)"
content = content.replace(old_tg, new_tg, 1)

# Also add to autonomous_velocity_loop's BTCTRY fetch
old_m5_tick = "m5_tick = await fetch_klines(\"BTCTRY\", \"5m\", 2)"
new_m5_tick = "await _velocity_rate_acquire()\n                    m5_tick = await fetch_klines(\"BTCTRY\", \"5m\", 2)"
# Only replace the second one (inside the while loop, not the init)
count = 0
def replace_second_m5(m):
    global count
    count += 1
    if count == 2:
        return new_m5_tick
    return m5_group  # won't work with simple replace, let me do it differently

# Actually let me just do a targeted replace for the first occurrence in while loop
idx_init = content.find("await fetch_klines(\"BTCTRY\", \"5m\", 2)")
if idx_init >= 0:
    idx_second = content.find("await fetch_klines(\"BTCTRY\", \"5m\", 2)", idx_init + 100)
    if idx_second >= 0:
        content = content[:idx_second] + "await _velocity_rate_acquire()\n                    " + content[idx_second:]

with open(r'D:\scalperagent_v4\backend\app\routers\velocity.py', 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
import ast
try:
    ast.parse(content)
    print('PASS: velocity.py compiles without syntax errors')
except SyntaxError as e:
    print(f'FAIL: {e}')

stats = content.count('_velocity_rate_acquire')
print(f'_velocity_rate_acquire calls: {stats}')
