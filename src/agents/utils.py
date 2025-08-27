import os

import aiohttp
from beeai_framework.backend import ChatModel
from beeai_framework.tools import Tool
from dotenv import load_dotenv

from agents.session_manager import SessionManager

load_dotenv()

model = os.getenv("MODEL", "openai:gpt-5-nano")
llm = ChatModel.from_name(model, {"api_key": os.getenv("API_KEY")})

# Shared singleton instance
session_manager = SessionManager()


class ToolNotFoundError(Exception):
    """Raised when required tools are not available."""

    pass


async def get_tools_by_names(tools: list[Tool], tool_names: list[str]) -> list[Tool]:
    """Get tools by names with comprehensive error handling.

    Args:
        tools: List of available tools.
        tool_names: List of required tool names.

    Returns:
        list[Tool]: List of matching tools.

    Raises:
        ToolNotFoundError: If any required tools are not found.
    """
    available_tools = []
    missing_tools = []

    for tool_name in tool_names:
        matching_tools = [tool for tool in tools if tool.name == tool_name]
        if matching_tools:
            available_tools.extend(matching_tools)
        else:
            missing_tools.append(tool_name)

    if missing_tools:
        available_tool_names = [tool.name for tool in tools]
        raise ToolNotFoundError(f"Required tools {missing_tools} not found. Available tools: {available_tool_names}")

    return available_tools


async def fetch_content(url: str) -> str:
    """Fetch content from provided URL"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    print(f"Failed to fetch content: {response.status}")
                    return ""
    except Exception as e:
        print(f"Error fetching content: {e}")
        return ""
