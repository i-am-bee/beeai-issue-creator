import contextlib
from typing import Any, Optional

from beeai_framework.adapters.openai import OpenAIChatModel
from beeai_framework.backend import ChatModelParameters, ChatModel
from beeai_framework.backend.utils import load_model
from beeai_framework.tools.mcp import MCPTool
from beeai_sdk.a2a.extensions import LLMFulfillment
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

class SessionContext:
    def __init__(self, llm_fulfillment: LLMFulfillment, github_pat: str, github_repository: str, docs_url: str, bug_template_url: str, feature_template_url: str):
        self._llm_fulfillment = llm_fulfillment
        self._github_pat = github_pat
        self._github_repository = github_repository
        self._docs_url = docs_url
        self._bug_template_url = bug_template_url
        self._feature_template_url = feature_template_url
        self._session: Optional[ClientSession] = None
        self._streams: Optional[Any] = None
        self._tools: Optional[list[MCPTool]] = None

    async def get_session(self) -> ClientSession:
        if self._session is None:
            await self.connect()
        return self._session
    
    def get_repository(self) -> str:
        return self._github_repository
    
    def get_docs_url(self) -> str:
        return self._docs_url
    
    def get_bug_template_url(self) -> str:
        return self._bug_template_url
    
    def get_feature_template_url(self) -> str:
        return self._feature_template_url
    
    def get_llm(self) -> LLMFulfillment:
        with contextlib.suppress(Exception):
            target_provider: type[ChatModel] = load_model(self._llm_fulfillment.api_model.replace("beeai:", "").replace("rits:", "ollama:"), "chat")
            tool_choice_support = target_provider.tool_choice_support.copy()

        return OpenAIChatModel(
            model_id=self._llm_fulfillment.api_model,
            base_url=self._llm_fulfillment.api_base,
            api_key=self._llm_fulfillment.api_key,
            parameters=ChatModelParameters(temperature=0.0),
            tool_choice_support=tool_choice_support,
        )

    async def get_tools(self) -> list[MCPTool]:
        if self._tools is None:
            session = await self.get_session()
            self._tools = await MCPTool.from_session(session)
        return self._tools

    async def connect(self):
        headers = {
            "Authorization": f"Bearer {self._github_pat}",
            "Accept": "application/json",
        }

        self._streams = streamablehttp_client("https://api.githubcopilot.com/mcp/x/issues", headers=headers)
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
