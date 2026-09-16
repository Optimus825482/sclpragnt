"""Python 3.11 uyumluluk muhafızı (2026-09-16 — DEPLOY ÇÖKÜŞÜ KÖK NEDENİ).

OLAY:
    `main.py` içinde şu satır vardı:

        f"... errors={len(hydration.get("errors", []) or [])}"

    f-string içinde AYNI TÜR tırnak kullanmak **PEP 701** özelliğidir ve yalnızca
    Python 3.12+ ile çalışır. Konteyner `python:3.11-slim` olduğu için bu satır
    SyntaxError üretti → backend HİÇ import edilemedi → konteyner ~2 saniyede öldü
    → Coolify "container backend is unhealthy" ile deploy'u düşürdü.

    Geliştirme makinesi Python **3.12.10** olduğu için `pytest` ve tüm 1096 test
    bunu GÖREMEDİ: kod yerelde sorunsuz parse ediliyor, sunucuda edilmiyor.

NEDEN `ast.parse(feature_version=(3,11))` YETMİYOR:
    Ölçüldü — `feature_version` PEP 701 iç içe tırnağı YAKALAMIYOR (3.12'nin
    tokenizer'ı her durumda kabul ediyor). Bu yüzden token akışı doğrudan taranır:
    bir f-string'in İÇİNDE, kapsayan f-string ile AYNI tırnak karakterini kullanan
    başka bir string/f-string görülürse bu 3.11'de SyntaxError demektir.
"""
import io
import pathlib
import sys
import tokenize
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCAN_DIRS = ("app", "scripts")
QUOTE_CHARS = ("'", '"')


def _quote_of(token_string: str) -> str:
    """Token'ın string sınırlayıcısını döndür ('f"' -> '"', 'rf\"\"\"' -> '\"\"\"')."""
    stripped = token_string
    while stripped and stripped[0].isalpha():
        stripped = stripped[1:]
    run = ""
    for ch in stripped:
        if ch in QUOTE_CHARS:
            run += ch
        else:
            break
    return run


def _delimiter_len(run: str) -> int:
    """Tırnak dizisinin SINIRLAYICI uzunluğu: Python'da her zaman 1 ya da 3.

    Boş string token'ı `""` iki tırnak içerir ama sınırlayıcısı TEK tırnaktır;
    `""""""` (boş üçlü string) ise 6 tırnak ama sınırlayıcısı ÜÇ'tür. Bu
    normalizasyon olmadan `f""` / `""` gibi boş string'ler yanlış pozitif üretir.
    """
    if not run:
        return 0
    return 3 if len(run) >= 3 else 1


def find_pep701_nesting(source: str) -> list[tuple[int, str]]:
    """3.11'de SyntaxError olacak f-string iç içe tırnağı kullanan satırları bul.

    KURAL (Python < 3.12 f-string kısıtı):
        Dış f-string'in sınırlayıcısı taranırken içerideki tırnak onu erken
        KAPATABİLİYORSA sözdizimi hatasıdır. Bu iki koşulun BİRLİKTE olmasıdır:

          1. AYNI tırnak karakteri (iç ' dış " ise sorun yok), ve
          2. iç sınırlayıcı dış sınırlayıcıdan KISA OLMAMALI (iç >= dış).

            dış tek " (1), iç tek "  (1) -> aynı + 1>=1 -> HATA
            dış tek " (1), iç tek '  (1) -> farklı      -> OK
            dış üçlü " (3), iç tek " (1) -> aynı + 1>=3 -> OK (üretimde çalışıyor)
            dış üçlü " (3), iç üçlü "(3) -> aynı + 3>=3 -> HATA

    Dönen: [(satır_no, token_metni), ...]
    """
    violations: list[tuple[int, str]] = []
    stack: list[tuple[str, int]] = []      # (tırnak karakteri, sınırlayıcı uzunluğu)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Zaten parse edilemiyorsa başka bir test/hata konusudur.
        return []

    def _violates(token_string: str) -> bool:
        if not stack:
            return False
        outer_char, outer_len = stack[-1]
        run = _quote_of(token_string)
        if not run:
            return False
        inner_len = _delimiter_len(run)
        return run[0] == outer_char and inner_len >= outer_len

    for tok in tokens:
        ttype, tstring = tok.type, tok.string
        if ttype == tokenize.FSTRING_START:
            if _violates(tstring):
                violations.append((tok.start[0], tstring))
            run = _quote_of(tstring)
            stack.append((run[0] if run else '"', _delimiter_len(run)))
        elif ttype == tokenize.FSTRING_END:
            if stack:
                stack.pop()
        elif ttype == tokenize.STRING and _violates(tstring):
            violations.append((tok.start[0], tstring))
    return violations


class Pep701NestingGuard(unittest.TestCase):
    """Depoyu 3.11 ile uyumsuz f-string iç içe tırnaklarına karşı koru."""

    def test_guard_detects_the_real_deploy_crash(self):
        """Muhafızın kendisi, deploy'u düşüren GERÇEK satırı yakalamalı."""
        bad = 'x = 1\nprint(f"a={len(d.get("k", []) or [])}")\n'
        found = find_pep701_nesting(bad)
        self.assertTrue(found, "muhafız gerçek deploy çöküşünü yakalamıyor")

    def test_guard_allows_single_quotes_inside_double_quoted_fstring(self):
        """Klasik 3.11-uyumlu kalıp YANLIŞ ALARM vermemeli."""
        good = 'print(f"a={len(d.get(\'k\', []) or [])}")\n'
        self.assertEqual([], find_pep701_nesting(good))

    def test_guard_allows_separate_statements(self):
        good = 'd = {}\nn = len(d.get("k", []) or [])\nprint(f"n={n}")\n'
        self.assertEqual([], find_pep701_nesting(good))

    def test_guard_detects_nested_fstring_same_quote(self):
        bad = 'print(f"a={f"{x}"}")\n'
        self.assertTrue(find_pep701_nesting(bad))

    def test_backend_app_is_python_311_compatible(self):
        """Tüm backend/app/**/*.py dosyaları 3.11 f-string kurallarına uymalı."""
        offenders: list[str] = []
        for base in SCAN_DIRS:
            for path in sorted((ROOT / base).rglob("*.py")):
                source = path.read_text(encoding="utf-8")
                for line_no, token_text in find_pep701_nesting(source):
                    rel = path.relative_to(ROOT).as_posix()
                    offenders.append(f"{rel}:{line_no} -> {token_text}")
        self.assertEqual(
            [], offenders,
            "Python 3.11'de SyntaxError üretecek f-string iç içe tırnak bulundu "
            "(konteyner python:3.11-slim kullanır):\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
