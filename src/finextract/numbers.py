"""Number parsing and scale handling for financial text."""
import re

SCALES = {"units": 1, "ones": 1, "thousands": 1e3, "millions": 1e6, "billions": 1e9}
_NUMBER = re.compile(r"\(?-?\$?\s*\d[\d,]*(?:\.\d+)?\)?")
_SCALE_HINT = re.compile(r"in\s+(thousands|millions|billions)", re.I)


def parse_number(s):
    """'$ 1,234.5' -> 1234.5 ; '(1,234)' -> -1234 ; '—' -> None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    if not t or t in {"—", "–", "-", "N/A", "n/a"}:
        return None
    neg = t.startswith("(") and t.rstrip("%").endswith(")") or t.startswith("-")
    digits = re.sub(r"[^\d.]", "", t)
    if not digits or digits == ".":
        return None
    try:
        v = float(digits)
    except ValueError:
        return None
    return -v if neg else v


def find_numbers(text):
    return [m.group(0) for m in _NUMBER.finditer(text)]


def detect_scale(text):
    """Look for '(in millions, except per share amounts)' style hints."""
    m = _SCALE_HINT.search(text)
    return m.group(1).lower() if m else "units"


def apply_scale(value, scale):
    if value is None:
        return None
    return value * SCALES.get((scale or "units").lower(), 1)


def numbers_match(a, b, rel_tol=0.005):
    if a is None or b is None:
        return False
    if a == b:
        return True
    return abs(a - b) <= rel_tol * max(abs(a), abs(b))


def normalize_ws(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()
