"""Claude Agent SDK wrapper.

Uses ``ClaudeSDKClient`` (persistent CLI subprocess) for multi-turn session
latency — subsequent turns within the same FRIDAY session reuse the same
client, skipping ~500ms-1s of subprocess spawn overhead per turn.

``ask_oneshot`` wraps :func:`claude_agent_sdk.query` for fire-and-forget
calls (e.g. session summarisation, weekly review orchestration)."""

from __future__ import annotations

from typing import Optional

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    query,
)

from .tools import ALLOWED_TOOL_NAMES, build_server


class Brain:
    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model
        self.server = build_server()
        self._client: Optional[ClaudeSDKClient] = None

    def _make_options(self, system_prompt: str) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            mcp_servers={"friday": self.server},
            allowed_tools=ALLOWED_TOOL_NAMES,
            setting_sources=[],
            permission_mode="bypassPermissions",
        )

    async def start_session(self, system_prompt: str) -> None:
        """Open a persistent client for the upcoming session."""
        await self.end_session()
        self._client = ClaudeSDKClient(options=self._make_options(system_prompt))
        await self._client.connect()

    async def ask(self, user_text: str) -> str:
        """Ask the current persistent session. Call ``start_session`` first."""
        if self._client is None:
            raise RuntimeError("brain.ask called before start_session")
        await self._client.query(user_text)
        final = ""
        async for msg in self._client.receive_response():
            if isinstance(msg, ResultMessage):
                final = getattr(msg, "result", "") or final
        return final

    async def end_session(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    async def ask_oneshot(self, user_text: str, system_prompt: str) -> str:
        """One-shot call outside an active session (e.g. summarisation)."""
        options = self._make_options(system_prompt)
        final = ""
        async for msg in query(prompt=user_text, options=options):
            if isinstance(msg, ResultMessage):
                final = getattr(msg, "result", "") or final
        return final
