from collections.abc import AsyncGenerator

from acp_sdk import Annotations, Metadata
from acp_sdk.models import Message
from acp_sdk.models.platform import PlatformUIAnnotation, PlatformUIType
from acp_sdk.server import Context, RunYield, RunYieldResume
from beeai_framework.agents.experimental import RequirementAgent
from beeai_framework.agents.experimental.requirements.conditional import ConditionalRequirement
from beeai_framework.memory import UnconstrainedMemory
from beeai_framework.middleware.trajectory import GlobalTrajectoryMiddleware
from beeai_framework.tools import Tool

from agents.server_instance import server
from agents.utils import ToolNotFoundError, get_tools_by_names, llm, session_manager


async def get_agent_find_duplicates():
    """Create and configure the GitHub duplicate issue finder agent.

    Returns:
        RequirementAgent: Configured agent with GitHub search tools for finding duplicate issues.

    Raises:
        RuntimeError: If required GitHub tools (get_issue, list_issues, search_issues) are not available.
    """
    tools = await session_manager.get_tools()
    tool_names = ["get_issue", "list_issues", "search_issues"]

    try:
        available_tools = await get_tools_by_names(tools, tool_names)
    except ToolNotFoundError as e:
        raise RuntimeError(f"Failed to configure duplicate finder agent: {e}") from e

    instruction = """
You are an expert GitHub issue duplicate detector. You are part of a multi-agent system. Your job is to analyze a given issue title and description and search for similar existing issues to identify potential duplicates.

## Instructions

When given an issue title and description, you should:

1. Use GitHub search tools to find similar issues using relevant keywords from the title and description
2. Search for issues with similar titles, keywords, and concepts
3. Analyze the search results to identify potential duplicates
4. Present your findings in a clear, structured format

Your response should include:

- **Search Summary**: Brief description of the search terms and strategy used
- **Potential Duplicates Found**: List of similar issues with:
  - Issue number and title
  - Brief similarity explanation
  - Link to the issue
- **Similarity Assessment**: Your assessment of how similar each found issue is (High/Medium/Low)
- **Recommendation**: Whether the new issue appears to be a duplicate or is sufficiently different

You have access to the following GitHub tools:
- search_issues: Search for issues using keywords
- list_issues: List issues in the repository
- get_issue: Get detailed information about a specific issue

Use these tools strategically to thoroughly search the repository for similar issues. Focus on finding issues with similar titles, descriptions, or concepts.

Write in a professional, neutral tone. Present your findings clearly and concisely."""

    return RequirementAgent(
        name="DuplicateIssueFinder",
        llm=llm,
        memory=UnconstrainedMemory(),
        instructions=instruction,
        tools=available_tools,
        requirements=[ConditionalRequirement(tool, max_invocations=3) for tool in available_tools],
    )


@server.agent(
    metadata=Metadata(
        annotations=Annotations(
            beeai_ui=PlatformUIAnnotation(ui_type=PlatformUIType.CHAT, display_name="GitHub Find Duplicates")
        )
    )
)
async def find_duplicates(input: list[Message], context: Context) -> AsyncGenerator[RunYield, RunYieldResume]:
    """GitHub duplicate issue finder agent that searches for similar existing issues.

    This agent analyzes issue titles and descriptions to identify potential duplicates
    by searching through existing GitHub issues using various search strategies.

    Args:
        input: List of messages containing issue details to search for duplicates.
        context: Agent execution context.

    Yields:
        RunYield: Analysis report with potential duplicates and similarity assessment.
    """
    agent = await get_agent_find_duplicates()
    prompt = str(input[-1])
    response = await agent.run(prompt=prompt).middleware(GlobalTrajectoryMiddleware(included=[Tool]))
    yield response.answer.text
