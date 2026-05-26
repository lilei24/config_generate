"""Small OpenAI-compatible chat completions client using only stdlib."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class OpenAICompatibleClient:
    """Client for vLLM/OpenAI-compatible ``/v1/chat/completions`` endpoints."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "EMPTY",
        timeout: float = 120,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    @property
    def chat_completions_url(self) -> str:
        return self.base_url + "/chat/completions"

    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        top_p: float = 1,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stop:
            payload["stop"] = stop
        if response_format:
            payload["response_format"] = response_format
        if extra_body:
            payload.update(extra_body)

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        request = urllib.request.Request(self.chat_completions_url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError("HTTP %s from %s: %s" % (exc.code, self.chat_completions_url, body)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Request failed for %s: %s" % (self.chat_completions_url, exc)) from exc


def first_message_content(response: Dict[str, Any]) -> str:
    """Extract assistant text from a chat completion response."""

    choices = response.get("choices")
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""
