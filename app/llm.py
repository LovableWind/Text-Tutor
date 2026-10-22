# -*- coding: utf-8 -*-
"""Streaming chat client for the two protocols a Chinese user is likely to use.

* ``anthropic`` — POST {base}/v1/messages  (DeepSeek's compatible endpoint)
* ``openai``    — POST {base}/chat/completions

Internal message format (shared by both):

    {"role": "user"|"assistant",
     "content": [{"type": "text", "text": "..."},
                 {"type": "image", "media_type": "image/png", "data": b"..."}]}
"""

from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class LLMError(Exception):
    def __init__(self, message: str, status: int = 0, code: str = "error"):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass
class StreamResult:
    text: str = ""
    thinking: str = ""
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = ""


PRESETS = {
    "anthropic": {
        "base_url": "https://api.deepseek.com/anthropic",
        "model": "deepseek-flash",
        "label": "DeepSeek 官方（Anthropic 兼容协议，支持图片）",
    },
    "openai": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "label": "OpenAI 兼容接口（任意厂商）",
    },
}


def _endpoint(base: str, protocol: str) -> str:
    base = (base or "").strip().rstrip("/")
    if protocol == "anthropic":
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _to_anthropic_content(content):
    out = []
    for block in content:
        if block["type"] == "text":
            if block.get("text"):
                out.append({"type": "text", "text": block["text"]})
        elif block["type"] == "image":
            out.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": block.get("media_type", "image/png"),
                        "data": base64.b64encode(block["data"]).decode("ascii"),
                    },
                }
            )
    return out


def _to_openai_content(content):
    if len(content) == 1 and content[0]["type"] == "text":
        return content[0]["text"]
    out = []
    for block in content:
        if block["type"] == "text":
            out.append({"type": "text", "text": block["text"]})
        elif block["type"] == "image":
            b64 = base64.b64encode(block["data"]).decode("ascii")
            media = block.get("media_type", "image/png")
            out.append(
                {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (media, b64)}}
            )
    return out


def stream_chat(
    settings: dict,
    system: str,
    messages: list,
    on_text=None,
    on_thinking=None,
    cancel=None,
) -> StreamResult:
    """Yield-free streaming: callbacks receive deltas as they arrive."""
    protocol = settings.get("protocol") or "anthropic"
    api_key = (settings.get("api_key") or "").strip()
    if not api_key:
        raise LLMError("还没有填写 API Key，请点右上角 ⚙ 设置。", code="no_key")

    model = settings.get("model") or PRESETS[protocol]["model"]
    base = settings.get("base_url") or PRESETS[protocol]["base_url"]
    url = _endpoint(base, protocol)
    max_tokens = int(settings.get("max_tokens") or 2048)
    temperature = float(settings.get("temperature") if settings.get("temperature") is not None else 0.6)

    if protocol == "anthropic":
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "system": system,
            "messages": [
                {"role": m["role"], "content": _to_anthropic_content(m["content"])}
                for m in messages
            ],
        }
        mode = settings.get("thinking") or "disabled"
        if mode == "enabled":
            body["thinking"] = {"type": "enabled", "budget_tokens": int(settings.get("thinking_budget") or 2048)}
        elif mode == "disabled":
            body["thinking"] = {"type": "disabled"}
        headers = {
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "accept": "text/event-stream",
        }
    else:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "messages": [{"role": "system", "content": system}]
            + [
                {"role": m["role"], "content": _to_openai_content(m["content"])}
                for m in messages
            ],
        }
        headers = {
            "content-type": "application/json",
            "authorization": "Bearer " + api_key,
            "accept": "text/event-stream",
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    result = StreamResult()
    try:
        resp = urllib.request.urlopen(req, timeout=180)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            raw = exc.read().decode("utf-8", "replace")
            data = json.loads(raw)
            err = data.get("error") or {}
            detail = err.get("message") if isinstance(err, dict) else str(err)
            detail = detail or raw[:400]
        except Exception:
            detail = str(exc)
        raise LLMError(_friendly_http(exc.code, detail), status=exc.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        raise LLMError("连不上模型服务：%s（检查网络或 Base URL）" % exc, code="network") from None
    except Exception as exc:  # pragma: no cover - defensive
        raise LLMError("请求失败：%s" % exc) from None

    try:
        if protocol == "anthropic":
            _read_anthropic(resp, result, on_text, on_thinking, cancel)
        else:
            _read_openai(resp, result, on_text, on_thinking, cancel)
    finally:
        try:
            resp.close()
        except Exception:
            pass
    return result


def _friendly_http(status: int, detail: str) -> str:
    hint = {
        401: "API Key 无效或已过期",
        403: "这个 Key 没有调用该模型的权限",
        404: "接口地址不对（检查 Base URL 是否要带 /v1）",
        422: "请求参数被拒绝",
        429: "请求太频繁，稍等几秒再试",
    }.get(status, "")
    tail = ("：" + detail) if detail else ""
    return "模型返回 %d%s%s" % (status, (" · " + hint) if hint else "", tail)


def _iter_sse(resp):
    buf = b""
    while True:
        chunk = resp.read(2048)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.rstrip(b"\r")
    if buf.strip():
        yield buf.strip()


def _read_anthropic(resp, result, on_text, on_thinking, cancel):
    for line in _iter_sse(resp):
        if cancel is not None and cancel.is_set():
            return
        if not line or not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            break
        try:
            event = json.loads(payload.decode("utf-8", "replace"))
        except Exception:
            continue
        etype = event.get("type")
        if etype == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                piece = delta.get("text") or ""
                if piece:
                    result.text += piece
                    if on_text:
                        on_text(piece)
            elif delta.get("type") == "thinking_delta":
                piece = delta.get("thinking") or ""
                if piece:
                    result.thinking += piece
                    if on_thinking:
                        on_thinking(piece)
        elif etype == "message_start":
            usage = (event.get("message") or {}).get("usage") or {}
            _absorb_usage(result.usage, usage)
        elif etype == "message_delta":
            usage = event.get("usage") or {}
            _absorb_usage(result.usage, usage)
            result.stop_reason = (event.get("delta") or {}).get("stop_reason") or result.stop_reason
        elif etype == "error":
            err = event.get("error") or {}
            raise LLMError(err.get("message") or "模型返回错误", code=str(err.get("type") or "error"))
        elif etype == "message_stop":
            break


def _read_openai(resp, result, on_text, on_thinking, cancel):
    for line in _iter_sse(resp):
        if cancel is not None and cancel.is_set():
            return
        if not line or not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            break
        try:
            event = json.loads(payload.decode("utf-8", "replace"))
        except Exception:
            continue
        if event.get("error"):
            err = event["error"]
            raise LLMError(str(err.get("message") or err), code="api")
        choices = event.get("choices") or []
        if not choices:
            if event.get("usage"):
                _absorb_usage(result.usage, event["usage"])
            continue
        delta = choices[0].get("delta") or {}
        piece = delta.get("content")
        if piece:
            result.text += piece
            if on_text:
                on_text(piece)
        think = delta.get("reasoning_content")
        if think:
            result.thinking += think
            if on_thinking:
                on_thinking(think)
        if choices[0].get("finish_reason"):
            result.stop_reason = choices[0]["finish_reason"]
        if event.get("usage"):
            _absorb_usage(result.usage, event["usage"])


def _absorb_usage(usage: Usage, raw: dict):
    if not isinstance(raw, dict):
        return
    usage.input_tokens = int(raw.get("input_tokens") or raw.get("prompt_tokens") or usage.input_tokens or 0)
    usage.output_tokens = int(
        raw.get("output_tokens") or raw.get("completion_tokens") or usage.output_tokens or 0
    )
    usage.cache_read = int(
        raw.get("cache_read_input_tokens")
        or (raw.get("prompt_tokens_details") or {}).get("cached_tokens")
        or usage.cache_read
        or 0
    )
    usage.cache_write = int(raw.get("cache_creation_input_tokens") or usage.cache_write or 0)


CLASSIFY_SYSTEM = (
    "你是分类器。判断学生选中的这段文字是不是「需要动手去做的题目」。\n"
    "A = 题目：需要求解、证明、计算、判断、填空，要学生自己动手。\n"
    "B = 陈述或提问：定理/定义的陈述、已给出的解答过程、或者只是问「这是什么/为什么」。\n"
    "只回答 A 或 B，不要解释。\n"
    "例：\n"
    "「设 f(x)=x^2，求 f'(1)」→ A\n"
    "「证明：若 A 可逆，则 det(A^-1)=1/det A」→ A\n"
    "「定理 1.4 单调有界数列必有极限」→ B\n"
    "「为什么这里可以取极限？」→ B\n"
    "「证明过程的第二步是取 N」→ B"
)


def classify_exercise(settings: dict, text: str):
    """Ask the model whether a selection is a task to solve.

    Returns True / False, or None when the answer is unusable.
    """
    if not text.strip():
        return None
    local = dict(settings)
    local["max_tokens"] = 4
    local["temperature"] = 0
    try:
        res = stream_chat(
            local,
            CLASSIFY_SYSTEM,
            [{"role": "user", "content": [{"type": "text", "text": text[:600]}]}],
        )
    except Exception:
        return None
    answer = (res.text or "").strip().upper()
    if answer.startswith("A"):
        return True
    if answer.startswith("B"):
        return False
    return None


def ping(settings: dict) -> str:
    """Round-trip a tiny request; returns the model's short answer."""
    res = stream_chat(
        {**settings, "max_tokens": 32, "temperature": 0},
        "你是连通性测试。只回复两个字：正常。",
        [{"role": "user", "content": [{"type": "text", "text": "测试"}]}],
    )
    return (res.text or "").strip() or "（空响应）"
