"""Small client for an OpenAI-compatible chat endpoint (vLLM, Ollama, llama.cpp server ...).

Posts are sent only after redaction, and by default only to a server on this machine: a remote
base_url is refused unless the config sets allow_remote: true, because that sends research data to
a third party (decide that with the ethics approval, not by accident).
"""
import os
import time
from urllib.parse import urlparse

import requests

from common.io import load_env

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class LLMClient:
    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None,
                 allow_remote: bool = False, timeout: float = 120, retries: int = 3, extra_body: dict | None = None):
        load_env()
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or "http://localhost:11434/v1").rstrip("/")
        host = urlparse(self.base_url).hostname or ""
        if host not in LOCAL_HOSTS and not allow_remote:
            raise PermissionError(f"LLM endpoint {self.base_url} is not local; set allow_remote: true in the "
                                  "config only if sending redacted posts there is covered by your ethics approval")
        self.model, self.timeout, self.retries = model, timeout, retries
        self.extra_body = extra_body or {}
        self.session = requests.Session()
        key = api_key or os.environ.get("LLM_API_KEY") or "none"
        self.session.headers["Authorization"] = f"Bearer {key}"

    def chat(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 64) -> tuple[str, dict, float]:
        """Return (text, usage, seconds)."""
        body = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                **self.extra_body}
        err = None
        for attempt in range(self.retries):
            t0 = time.perf_counter()
            try:
                r = self.session.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                data = r.json()
                text = data["choices"][0]["message"].get("content") or ""
                return text, data.get("usage") or {}, time.perf_counter() - t0
            except (requests.RequestException, KeyError, ValueError) as e:
                err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM request failed after {self.retries} attempts: {err}")
