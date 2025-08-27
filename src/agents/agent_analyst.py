from textwrap import dedent

from beeai_framework.agents.experimental import RequirementAgent
from beeai_framework.agents.experimental.requirements.conditional import ConditionalRequirement
from beeai_framework.middleware.trajectory import GlobalTrajectoryMiddleware
from beeai_framework.tools import Tool

from agents.utils import ToolNotFoundError, get_tools_by_names, llm, session_manager


async def get_agent_analyst():
    """Create and configure the duplicate issue analyzer agent."""
    tools = await session_manager.get_tools()
    tool_names = ["get_issue", "list_issues", "search_issues"]

    try:
        available_tools = await get_tools_by_names(tools, tool_names)
    except ToolNotFoundError as e:
        raise RuntimeError(f"Failed to configure duplicate finder agent: {e}") from e

    role = "helpful analyst"
    instruction = dedent(
        """\
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
        """
    )

    return RequirementAgent(
        name="Analyst",
        llm=llm,
        role=role,
        instructions=instruction,
        tools=available_tools,
        requirements=[ConditionalRequirement(tool, max_invocations=3) for tool in available_tools],
        middlewares=[GlobalTrajectoryMiddleware(included=[Tool])],
    )
