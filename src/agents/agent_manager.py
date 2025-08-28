import os
from textwrap import dedent

from beeai_framework.agents.experimental import RequirementAgent
from beeai_framework.agents.experimental.requirements.ask_permission import AskPermissionRequirement
from beeai_framework.agents.experimental.requirements.conditional import ConditionalRequirement
from beeai_framework.middleware.trajectory import GlobalTrajectoryMiddleware
from beeai_framework.tools import Tool
from beeai_framework.tools.handoff import HandoffTool
from beeai_framework.tools.think import ThinkTool

from agents.agent_analyst import get_agent_analyst
from agents.agent_writer import get_agent_writer
from agents.utils import ToolNotFoundError, get_tools_by_names, llm, session_manager


async def get_agent_manager():
    """Create and configure the issue workflow management agent."""
    tools = await session_manager.get_tools()

    try:
        tools = await get_tools_by_names(tools, ["create_issue"])
        create_issue = tools[0]
    except ToolNotFoundError as e:
        raise RuntimeError(f"Failed to configure the agent: {e}") from e

    repository = os.getenv("GITHUB_REPOSITORY")

    role = "helpful project manager"
    instruction = dedent(
        f"""\
        Your job is to hand off tasks to the right experts, run the process step by step, and keep all communication with the user.
        You don't do the actual writing yourself — you guide the workflow, keep the user in control, and ensure everything moves forward smoothly.

        You work in the following repository: {repository}

        ## Responsibilities
        You manage the full lifecycle of a GitHub issue — from user request to final creation.
        You keep all communication with the user, always validate with them before taking action, and make sure the process moves step by step.
        You don't do the actual writing yourself — you coordinate experts, guide the workflow, and keep the user in control.

        ## Workflow
        1. **Draft**
        - Use `transfer_to_writer`
        - Do not add, expand, interpret, or restructure the content yourself.
        - Never include your own assumptions, rationale, or formatting.
        - The writer is solely responsible for turning the raw input into a draft issue.

        2. **Iterate with the User**
        - Share the draft with the user.
        - Ask for feedback or changes.
        - Support multiple rounds of revision until the user explicitly approves the issue content.

        3. **Check duplicates**
        - After the user approves the draft, use `transfer_to_analyst` to search for similar issues.
        - If duplicates are found, present them to the user.
            - If the user decides it's a duplicate, stop the process.
            - If the user wants to continue, proceed with creation and note the duplicate context.
        - If no duplicates are found, continue.

        4. **Create the Issue**  
        - Only after explicit user confirmation (e.g., “approve,” “looks good,” “create it”), use create_issue to create the GitHub issue.
        - Confirm with the user once done by sending a `final_answer`.

        ## Guidelines
        - Always proceed step by step.
        - Use a professional, neutral tone.
        - Never mention agents, handoffs, or internal mechanisms.
        - Always return drafts wrapped in ```.
        - If the user input is unclear, ask clarifying questions.
        - Never skip the user feedback loop before creation.
        """
    )

    # Get the specialized agents
    writer = await get_agent_writer()
    analyst = await get_agent_analyst()

    handoff_writer = HandoffTool(
        target=writer,
        name="transfer_to_writer",
        description="Transfer to the Technical Writer to draft an issue.",
        # propagate_inputs=False,
    )

    handoff_analyst = HandoffTool(
        target=analyst,
        name="transfer_to_analyst",
        description="Transfer to the Analyst to search for similar issues.",
        # propagate_inputs=False,
    )

    return RequirementAgent(
        name="Project Manager",
        llm=llm,
        role=role,
        instructions=instruction,
        tools=[
            ThinkTool(),
            handoff_writer,
            handoff_analyst,
            create_issue,
        ],
        requirements=[
            ConditionalRequirement(ThinkTool, force_at_step=1, force_after=[Tool], consecutive_allowed=False),
            # AskPermissionRequirement(create_issue),
        ],
        middlewares=[GlobalTrajectoryMiddleware(included=[Tool])],
    )
