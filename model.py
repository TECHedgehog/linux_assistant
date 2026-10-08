"""Ollama request construction and communication."""

import json
import socket
import time
import urllib.error
import urllib.request

from config import MODEL, OLLAMA_RETRIES, OLLAMA_RETRY_BACKOFF, OLLAMA_TIMEOUT, OLLAMA_URL


def ollama_request(messages, tools=None):
    """Send a non-streaming chat request to Ollama and validate its response."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": tools or [],
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    for attempt in range(OLLAMA_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
                if getattr(response, "status", 200) >= 400:
                    raise RuntimeError(f"Ollama HTTP status {response.status}")
                body = response.read().decode("utf-8")
            parsed = json.loads(body)
            message = parsed.get("message") if isinstance(parsed, dict) else None
            if not isinstance(message, dict):
                raise RuntimeError("Ollama returned an invalid response")
            if not isinstance(message.get("content", ""), str):
                raise RuntimeError("Ollama message content must be text")
            return parsed
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned invalid JSON") from exc
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            if attempt >= OLLAMA_RETRIES:
                reason = getattr(exc, "reason", exc)
                raise RuntimeError(f"Could not connect to Ollama: {reason}") from exc
            time.sleep(OLLAMA_RETRY_BACKOFF)
