import os
from typing import Any, Optional

from beeai_framework.tools.mcp import MCPTool
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class SessionManager:
    def __init__(self):
        self._session: Optional[ClientSession] = None
        self._streams: Optional[Any] = None
        self._tools: Optional[list[MCPTool]] = None

    async def get_session(self) -> ClientSession:
        if self._session is None:
            await self.connect()
        return self._session

    async def get_tools(self) -> list[MCPTool]:
        if self._tools is None:
            session = await self.get_session()
            self._tools = await MCPTool.from_client(session)
        return self._tools

    async def connect(self):
        headers = {
            "Authorization": f"Bearer {os.getenv('GITHUB_PAT')}",
            "Accept": "application/json",
            "X-MCP-Toolsets": "issues,labels",
        }

        self._streams = streamablehttp_client("https://api.githubcopilot.com/mcp", headers=headers)
        streams = await self._streams.__aenter__()
        self._session = ClientSession(streams[0], streams[1])
        await self._session.__aenter__()
        await self._session.initialize()

    async def close(self):
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None
        if self._streams:
            await self._streams.__aexit__(None, None, None)
            self._streams = None
        self._tools = None
