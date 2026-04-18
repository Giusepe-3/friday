"""Claude Agent SDK wrapper.

Calls :func:`claude_agent_sdk.query` with our MCP server and allowed-tool
list. Iterates yielded messages, capturing the session id from the init
SystemMessage and the final text from the ResultMessage.

Auth note: the SDK inherits the active ``claude login`` session — no API
key is passed here; the user's Claude Max subscription provides quota."""

from __future__ import annotations

from typing import Optional

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    query,
)

from .tools import ALLOWED_TOOL_NAMES, build_server


class Brain:
    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model
        self.server = build_server()

    async def ask(
        self,
        user_text: str,
        system_prompt: str,
        session_id: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            mcp_servers={"friday": self.server},
            allowed_tools=ALLOWED_TOOL_NAMES,
            setting_sources=[],
            permission_mode="bypassPermissions",
            resume=session_id,
        )

        new_session_id = session_id
        final_text = ""

        async for msg in query(prompt=user_text, options=options):
            if isinstance(msg, SystemMessage) and getattr(msg, "subtype", None) == "init":
                data = getattr(msg, "data", None) or {}
                if isinstance(data, dict) and "session_id" in data:
                    new_session_id = data["session_id"]
            elif isinstance(msg, ResultMessage):
                final_text = getattr(msg, "result", "") or ""

        return final_text, new_session_id
