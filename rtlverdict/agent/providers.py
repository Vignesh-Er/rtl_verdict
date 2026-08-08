"""Wire-format adapters for the two supported backends: the Anthropic
Messages API (default) and any OpenAI-chat-completions-compatible endpoint
(selected by passing --base-url). Plain HTTP via `requests`, not the
Anthropic SDK: the SDK's own base_url override still speaks the Anthropic
Messages wire format to whatever host it points at, so it cannot reach a
genuinely OpenAI-shaped endpoint (different tool schema, different
message/result framing). Supporting both wire formats in one small,
inspectable harness is the actual requirement (model-agnostic loop, not
Anthropic-only with an unused override), which is what forces raw HTTP
here.

Kept separate from loop.py so the loop's own control flow stays close to
its ~200-line budget; these are pure request/response translation and are
independently testable against canned JSON with no API key and no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import requests


@dataclass
class NormalizedResponse:
    text: str
    tool_calls: list[dict]  # [{"id": str, "name": str, "input": dict}]
    stop_reason: str  # "tool_use" | "end_turn" | "max_tokens" | "other"
    input_tokens: int
    output_tokens: int
    raw: dict  # provider-native response body, kept for trajectory logging


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def request(
        self, model: str, system: str, messages: list, tools: list[dict],
        max_tokens: int, seed: int, timeout_s: int = 120,
    ) -> NormalizedResponse:
        # The Messages API has no seed parameter - `seed` is accepted here only
        # to keep the two providers' call signatures identical; Anthropic runs
        # do NOT claim seed-determinism (recorded in the trajectory regardless,
        # for reproducibility bookkeeping, per the standing "never claim more
        # than was actually produced" rule).
        del seed
        body: dict = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = requests.post(
            f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(b["text"] for b in data["content"] if b["type"] == "text")
        tool_calls = [
            {"id": b["id"], "name": b["name"], "input": b["input"]}
            for b in data["content"] if b["type"] == "tool_use"
        ]
        usage = data.get("usage", {})
        return NormalizedResponse(
            text=text, tool_calls=tool_calls, stop_reason=data.get("stop_reason", "other"),
            input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
            raw=data,
        )

    def append_assistant(self, messages: list, resp: NormalizedResponse) -> None:
        messages.append({"role": "assistant", "content": resp.raw["content"]})

    def append_tool_results(self, messages: list, results: list[dict]) -> None:
        messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r["tool_call_id"], "content": r["output"], "is_error": r["is_error"]}
                for r in results
            ],
        })


class OpenAICompatProvider:
    """Any endpoint speaking the OpenAI chat-completions wire format
    (function-calling tool shape, role='tool' results, native `seed`).
    Uses only the lowest-common-denominator request shape - no
    Anthropic-only features (adaptive thinking, effort) - matching the
    brief's requirement for a genuinely model-agnostic loop.
    """

    name = "openai-compatible"

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _to_openai_tools(tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
            }
            for t in tools
        ]

    def request(
        self, model: str, system: str, messages: list, tools: list[dict],
        max_tokens: int, seed: int, timeout_s: int = 120,
    ) -> NormalizedResponse:
        full_messages = [{"role": "system", "content": system}] + messages
        body: dict = {"model": model, "max_tokens": max_tokens, "messages": full_messages, "seed": seed}
        if tools:
            body["tools"] = self._to_openai_tools(tools)
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
            json=body,
            timeout=timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        text = msg.get("content") or ""
        tool_calls = [
            {"id": tc["id"], "name": tc["function"]["name"], "input": json.loads(tc["function"]["arguments"])}
            for tc in (msg.get("tool_calls") or [])
        ]
        finish = choice.get("finish_reason", "other")
        stop_reason = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens"}.get(finish, finish)
        usage = data.get("usage", {})
        return NormalizedResponse(
            text=text, tool_calls=tool_calls, stop_reason=stop_reason,
            input_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    def append_assistant(self, messages: list, resp: NormalizedResponse) -> None:
        msg = resp.raw["choices"][0]["message"]
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls")})

    def append_tool_results(self, messages: list, results: list[dict]) -> None:
        for r in results:
            messages.append({"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["output"]})


def make_provider(api_key: str, base_url: str | None):
    if base_url:
        return OpenAICompatProvider(api_key, base_url)
    return AnthropicProvider(api_key)
