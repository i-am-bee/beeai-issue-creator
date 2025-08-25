import json
import os
import re
from collections.abc import AsyncGenerator

from acp_sdk import Annotations, MessagePart, Metadata, TrajectoryMetadata
from acp_sdk.models import Message
from acp_sdk.models.platform import PlatformUIAnnotation, PlatformUIType
from acp_sdk.server import Context, RunYield, RunYieldResume
from beeai_framework.agents.experimental import RequirementAgent
from beeai_framework.agents.experimental.requirements.ask_permission import AskPermissionRequirement
from beeai_framework.agents.experimental.requirements.conditional import ConditionalRequirement
from beeai_framework.memory import UnconstrainedMemory
from beeai_framework.middleware.trajectory import GlobalTrajectoryMiddleware, Writeable
from beeai_framework.tools import Tool
from beeai_framework.tools.handoff import HandoffTool
from beeai_framework.tools.think import ThinkTool

from agents.agent_draft_issue import get_agent_draft_issue
from agents.agent_find_duplicates import get_agent_find_duplicates
from agents.server_instance import server
from agents.utils import ToolNotFoundError, get_tools_by_names, llm, session_manager, to_framework_message


class TrajectoryMessageWriter(Writeable):
    """Custom Writable target that yields MessagePart with TrajectoryMetadata"""

    def __init__(self, yield_fn):
        self.yield_fn = yield_fn

    def write(self, data):
        """Write trajectory data as MessagePart"""
        data_str = str(data).strip()

        # Parse: --> or <-- 🛠️ ToolName[tool_name][start|finish]: content
        match = re.match(r"(?:-->|<--) 🛠️ \w+\[(\w+)\]\[(start|finish)\]: (.+)", data_str)
        if match:
            tool_name, phase, content = match.groups()
            if phase == "start":
                message = "Started..."
                try:
                    tool_input = json.loads(content)
                except json.JSONDecodeError:
                    tool_input = {"raw": content}
            else:  # finish
                message = content.strip('"')
                tool_input = {}

            self.yield_fn(
                MessagePart(metadata=TrajectoryMetadata(tool_name=tool_name, tool_input=tool_input, message=message))
            )
        else:
            # Fallback
            self.yield_fn(
                MessagePart(metadata=TrajectoryMetadata(tool_name="Unknown", tool_input={}, message=data_str))
            )


async def get_agent_orchestrate():
    """Create and configure the GitHub orchestrator agent.

    This agent coordinates the GitHub issue creation workflow by managing handoffs
    between the issue drafter and duplicate finder agents, then creating the final issue.

    Returns:
        RequirementAgent: Configured orchestrator agent with handoff tools and workflow requirements.

    Raises:
        RuntimeError: If the create_issue tool is not available.
    """
    tools = await session_manager.get_tools()

    try:
        create_issue_tools = await get_tools_by_names(tools, ["create_issue"])
        create_issue_tool = create_issue_tools[0]
    except ToolNotFoundError as e:
        raise RuntimeError(f"Failed to configure orchestrator agent: {e}") from e

    repository = os.getenv("GITHUB_REPOSITORY")
    instruction = f"""You are an orchestrator.
You do not enrich or add content yourself.  
Your job is to hand off tasks to the right experts, guide the workflow, and keep the user in control.

You work in the following repository: {repository}

## Responsibilities
You manage the **full lifecycle of a GitHub issue** — from user request to final creation — always validating with the user before taking action.

## Workflow
1. **Draft**  
   - Use `transfer_to_issue_drafter` to generate a draft based only on the user’s input.  
   - Do not add or expand details yourself.

2. **Check duplicates**  
   - Use `transfer_to_duplicate_finder` to search for duplicates.  
   - If duplicates are found, present them to the user for review and wait for confirmation before proceeding.  
   - If no duplicates are found, continue.

3. **Iterate with the User**  
   - Share the draft with the user.  
   - Ask for feedback or changes.  
   - Support multiple rounds of revision until the user explicitly approves the issue content.

4. **Create the Issue**  
   - After user approval, use `create_issue` to create the actual GitHub issue.  
   - Confirm with the user once done by sending a `final_answer`.

## Guidelines
- Always proceed step by step.  
- Use a professional, neutral tone.  
- Never mention agents, handoffs, or internal mechanisms.  
- Always return drafts wrapped in ```.  
- If the user input is unclear, ask clarifying questions.  
- Never skip the user feedback loop before creation.  
"""

    # Get the specialized agents
    draft_issue_agent = await get_agent_draft_issue()
    find_duplicates_agent = await get_agent_find_duplicates()

    handoff_draft = HandoffTool(
        target=draft_issue_agent,
        name="transfer_to_issue_drafter",
        description="Transfer to the GitHub Issue Drafter to draft an issue.",
    )

    handoff_find_duplicates = HandoffTool(
        target=find_duplicates_agent,
        name="transfer_to_duplicate_finder",
        description="Transfer to the GitHub Find Duplicates to search for relevant issues.",
    )

    return RequirementAgent(
        llm=llm,
        memory=UnconstrainedMemory(),
        instructions=instruction,
        tools=[
            ThinkTool(),
            handoff_draft,
            handoff_find_duplicates,
            create_issue_tool,
        ],
        requirements=[
            ConditionalRequirement(ThinkTool, force_at_step=1),
            ConditionalRequirement(handoff_find_duplicates, only_after=[handoff_draft]),
            AskPermissionRequirement(create_issue_tool),
        ],
    )


@server.agent(
    metadata=Metadata(
        annotations=Annotations(
            beeai_ui=PlatformUIAnnotation(ui_type=PlatformUIType.CHAT, display_name="GitHub Issue Creator")
        )
    )
)
async def orchestrate(input: list[Message], context: Context) -> AsyncGenerator[RunYield, RunYieldResume]:
    """GitHub orchestrator agent that coordinates the complete issue creation workflow.

    This agent manages a multi-step process: drafting an issue, checking for duplicates,
    and creating the final GitHub issue. It uses conditional requirements to enforce
    the proper workflow sequence and handoff coordination.

    Args:
        input: List of messages describing the issue to be created.
        context: Agent execution context.

    Yields:
        RunYield: Results from the orchestrated workflow including draft, duplicate check, and final issue creation.
    """
    agent = await get_agent_orchestrate()

    history = [message async for message in context.session.load_history()]
    framework_messages = [to_framework_message(message.role, str(message)) for message in history + input]
    await agent.memory.add_many(framework_messages)

    prompt = str(input[-1])

    def trajectory_yield(message_part):
        context.yield_sync(message_part)

    trajectory_writer = TrajectoryMessageWriter(trajectory_yield)
    A2ATrajectoryMiddleware = GlobalTrajectoryMiddleware(included=[Tool], target=trajectory_writer)

    response = await agent.run(prompt=prompt).middleware(A2ATrajectoryMiddleware)
    yield response.answer.text
