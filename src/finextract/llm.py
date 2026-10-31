"""Extraction backends.

- heuristic : no LLM, regex over table rows. A real non-LLM baseline to beat (and free).
- anthropic : Claude via the Messages API (needs ANTHROPIC_API_KEY).
- openai    : any OpenAI-compatible endpoint (needs OPENAI_API_KEY; set OPENAI_BASE_URL
              for Ollama http://localhost:11434/v1, Groq, Together, etc. — local Ollama is free).
"""
import json
import logging
import os
import re
import time

import requests

from .numbers import detect_scale, find_numbers

log = logging.getLogger(__name__)

SYSTEM = (
    "You extract figures from SEC 10-K filings. Use only the excerpts provided. "
    "Respond with a single JSON object and nothing else."
)

PROMPT = """Company: {company}
Fiscal year ended: {period}
Field: {field} — {description}

Excerpts from the 10-K:
{context}

Return JSON exactly in this shape:
{{"value": <the number as printed for the fiscal year above, digits only, negative if shown in parentheses, or null if not present>,
  "scale": "<units|thousands|millions|billions — the scale stated for that table or sentence>",
  "quote": "<the exact line from the excerpts that contains the value>"}}"""


def build_prompt(field, company, period, chunks):
    context = "\n\n".join(f"[Excerpt {i + 1}]\n{c}" for i, c in enumerate(chunks))
    return PROMPT.format(company=company, period=period, field=field.name,
                         description=field.description, context=context)


def parse_json_response(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"value": None, "scale": "units", "quote": "", "parse_error": True}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"value": None, "scale": "units", "quote": "", "parse_error": True}
    return {"value": obj.get("value"), "scale": obj.get("scale") or "units", "quote": obj.get("quote") or ""}


class HeuristicProvider:
    name = "heuristic"

    def extract(self, field, company, period, chunks):
        for chunk in chunks:
            scale = detect_scale(chunk)
            for line in chunk.splitlines():
                cells = [c.strip() for c in line.split("|")]
                if len(cells) < 2:
                    continue
                label = cells[0].lower().rstrip(":")
                if any(label == a or label.startswith(a) for a in field.aliases):
                    nums = [n for c in cells[1:] for n in find_numbers(c)]
                    if nums:
                        return {"value": nums[0], "scale": "units" if field.unit != "USD" else scale,
                                "quote": line, "usage": {}}
        return {"value": None, "scale": "units", "quote": "", "usage": {}}


class AnthropicProvider:
    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model=None, max_tokens=300):
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise SystemExit("Set ANTHROPIC_API_KEY to use --provider anthropic")
        self.model = model or os.environ.get("FINEXTRACT_MODEL", "claude-haiku-5-5")
        self.max_tokens = max_tokens

    def extract(self, field, company, period, chunks):
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": SYSTEM,
                "messages": [{"role": "user", "content": build_prompt(field, company, period, chunks)}]}
        headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        data = _post_with_retry(self.URL, headers, body)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        out = parse_json_response(text)
        u = data.get("usage", {})
        out["usage"] = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
        return out


class OpenAICompatProvider:
    name = "openai"

    def __init__(self, model=None, max_tokens=300):
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.key = os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("FINEXTRACT_MODEL")
        if not self.model:
            raise SystemExit("Pass --model (e.g. llama3.1 for Ollama) to use --provider openai")
        if not self.key and "localhost" not in self.base and "127.0.0.1" not in self.base:
            raise SystemExit("Set OPENAI_API_KEY (or OPENAI_BASE_URL to a local server)")
        self.max_tokens = max_tokens
        # Ollama silently truncates prompts longer than its context window (num_ctx), so warn first.
        self.context_tokens = int(os.environ.get("FINEXTRACT_CONTEXT_TOKENS")
                                  or os.environ.get("OLLAMA_CONTEXT_LENGTH") or 8192)
        self.json_mode = True
        self._warned_context = False
        # Local thinking models (Qwen 3.5, Gemma 4) otherwise spend max_tokens on hidden reasoning
        # and return empty content. Dropped together with JSON mode if the server rejects it.
        local = "localhost" in self.base or "127.0.0.1" in self.base
        self.reasoning_effort = os.environ.get("FINEXTRACT_REASONING_EFFORT", "none" if local else "")

    def _check_context(self, prompt):
        est = (len(SYSTEM) + len(prompt)) // 4 + self.max_tokens  # ~4 chars per token
        if est > self.context_tokens and not self._warned_context:
            self._warned_context = True
            log.warning("prompt ~%d tokens (incl. %d output) exceeds context %d; the server may truncate it. "
                        "Raise the server's context or lower --k.", est, self.max_tokens, self.context_tokens)
        return est

    def extract(self, field, company, period, chunks):
        prompt = build_prompt(field, company, period, chunks)
        self._check_context(prompt)
        body = {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": prompt}]}
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        url = f"{self.base}/chat/completions"
        if self.json_mode:
            extra = {"response_format": {"type": "json_object"}}
            if self.reasoning_effort:
                extra["reasoning_effort"] = self.reasoning_effort
            try:
                data = _post_with_retry(url, headers, {**body, **extra})
            except RuntimeError as e:
                if not str(e).startswith(("400", "422")):
                    raise
                self.json_mode = False
                log.warning("server rejected %s (%s); continuing without JSON mode",
                            json.dumps(extra), str(e)[:120])
                data = _post_with_retry(url, headers, body)
        else:
            data = _post_with_retry(url, headers, body)
        out = parse_json_response(data["choices"][0]["message"]["content"])
        u = data.get("usage", {})
        out["usage"] = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}
        return out


def _post_with_retry(url, headers, body, retries=5):
    for attempt in range(retries):
        r = requests.post(url, headers=headers, json=body, timeout=float(os.environ.get("FINEXTRACT_TIMEOUT", 600)))
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(min(30, 2 ** attempt))
            continue
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    raise RuntimeError(f"gave up after {retries} retries: {r.status_code}")


def get_provider(name, model=None):
    if name == "heuristic":
        return HeuristicProvider()
    if name == "anthropic":
        return AnthropicProvider(model)
    if name == "openai":
        return OpenAICompatProvider(model)
    raise SystemExit(f"Unknown provider: {name}")
