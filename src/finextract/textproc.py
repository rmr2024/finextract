"""Turn 10-K HTML (usually inline XBRL) into searchable text chunks."""
import os
import re
import warnings
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .numbers import detect_scale

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

try:
    import lxml  # noqa: F401
    _PARSER = "lxml"
except ImportError:
    _PARSER = "html.parser"

_WS = re.compile(r"[ \t  ​]+")


def html_to_text(html):
    """Convert filing HTML to plain text. Tables become one ' | '-separated line per row."""
    soup = BeautifulSoup(html, _PARSER)
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    # The iXBRL header holds hidden facts that never appear on the rendered page.
    for tag in soup.find_all(lambda t: t.name and t.name.lower() in ("ix:header",)):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display:\s*none", re.I)):
        tag.decompose()

    for table in soup.find_all("table"):
        lines = []
        for tr in table.find_all("tr"):
            cells = [_WS.sub(" ", td.get_text(" ", strip=True)).strip() for td in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c and c != "$"]
            cells = _merge_paren_cells(cells)
            if cells:
                lines.append(" | ".join(cells))
        table.replace_with(soup.new_string("\n" + "\n".join(lines) + "\n"))

    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
        block.insert_after("\n")

    text = soup.get_text()
    lines = [_WS.sub(" ", l).strip() for l in text.splitlines()]
    out, blank = [], 0
    for l in lines:
        if l:
            out.append(l)
            blank = 0
        elif blank == 0:
            out.append("")
            blank = 1
    return "\n".join(out).strip()


def _merge_paren_cells(cells):
    """Filings often split '(1,234' and ')' into separate cells; glue them back."""
    merged = []
    for c in cells:
        if c in (")", ")%", "%") and merged:
            merged[-1] += c
        else:
            merged.append(c)
    return merged


def chunk_text(text, max_chars=1800, overlap_lines=3):
    """Line-based chunks so table rows are never cut in half.

    A chunk without its own "(In millions)"-style hint inherits the most recent one seen,
    as a "[amounts in <scale>]" first line, so table rows split from their header keep their scale.
    """
    lines = text.splitlines()
    chunks, cur, size, scale = [], [], 0, None

    def emit(cur):
        body = "\n".join(cur)
        if scale and detect_scale(body) == "units":
            body = f"[amounts in {scale}]\n{body}"
        chunks.append(body)

    for line in lines:
        if size + len(line) > max_chars and cur:
            emit(cur)
            cur = cur[-overlap_lines:] if overlap_lines else []
            size = sum(len(x) for x in cur)
        cur.append(line)
        size += len(line) + 1
        hint = detect_scale(line)
        if hint != "units":
            scale = hint
    if cur:
        emit(cur)
    return chunks


def load_filing_text(html_path, cache_dir="data/text"):
    cache = Path(cache_dir) / (Path(html_path).stem + ".txt")
    if cache.exists() and cache.stat().st_size > 0:
        return cache.read_text(encoding="utf-8")
    text = html_to_text(Path(html_path).read_bytes())
    cache.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file then rename, so an interrupted run never leaves a partial cache.
    tmp = cache.with_suffix(".txt.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, cache)
    return text
