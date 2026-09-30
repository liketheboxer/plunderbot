"""Thin clients for the outside services: Claude (Anthropic) for Parley and the Ship's Ledger, and Kagi FastGPT.

Plain aiohttp, no SDKs, so there's nothing extra to install. Keys come from Exocomp secrets.
"""
from __future__ import annotations

import aiohttp

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
KAGI_URL = "https://kagi.com/api/v0/fastgpt"


class AIError(RuntimeError):
    def __init__(self, service: str, status: int | None, detail: str):
        super().__init__(f"{service} {status or ''}: {detail}".strip())
        self.service, self.status, self.detail = service, status, detail


class _Client:
    def __init__(self, timeout: float = 45):
        self._session: aiohttp.ClientSession | None = None
        self._timeout = timeout

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout))
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()


class Claude(_Client):
    def __init__(self, api_key: str, model: str):
        super().__init__()
        self.api_key, self.model = api_key, model

    async def create(self, *, system: str, messages: list[dict], tools: list[dict] | None = None,
                     max_tokens: int = 600, allow_tools: bool = True, tool_choice: dict | None = None) -> dict:
        body = {"model": self.model, "max_tokens": max_tokens, "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
            if tool_choice is not None:  # e.g. {"type": "tool", "name": ...} to always fill in a form
                body["tool_choice"] = tool_choice
            elif not allow_tools:  # tools stay declared (earlier turns used them) but it must answer now
                body["tool_choice"] = {"type": "none"}
        headers = {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION,
                   "content-type": "application/json"}
        session = await self.session()
        async with session.post(ANTHROPIC_URL, json=body, headers=headers) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200:
                err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
                raise AIError("Claude", resp.status, err.get("message") or str(data)[:200])
            return data


class Kagi(_Client):
    def __init__(self, api_key: str):
        super().__init__(timeout=30)
        self.api_key = api_key

    async def fastgpt(self, query: str) -> tuple[str, list[dict]]:
        """(answer, references) for a question, answered from a live web search."""
        session = await self.session()
        async with session.post(KAGI_URL, json={"query": query},
                                headers={"Authorization": f"Bot {self.api_key}"}) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200 or not isinstance(data, dict) or "data" not in data:
                errors = data.get("error") if isinstance(data, dict) else None
                raise AIError("Kagi", resp.status, str(errors or data)[:200])
            d = data["data"] or {}
            return d.get("output") or "", d.get("references") or []
