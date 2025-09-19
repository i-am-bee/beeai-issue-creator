import json
from textwrap import dedent, indent

from beeai_framework.agents.experimental import RequirementAgent
from beeai_framework.agents.experimental.prompts import (
    RequirementAgentSystemPromptInput,
)
from beeai_framework.agents.experimental.requirements.conditional import ConditionalRequirement
from beeai_framework.memory import BaseMemory
from beeai_framework.middleware.trajectory import GlobalTrajectoryMiddleware
from beeai_framework.template import PromptTemplate, PromptTemplateInput
from beeai_framework.tools import Tool
from beeai_framework.tools.handoff import HandoffTool

from agents.agent_analyst import get_agent_analyst
from agents.agent_writer import get_agent_writer
from agents.session_context import SessionContext
from agents.simple_think import SimpleThinkTool
from agents.utils import ToolNotFoundError, create_repo_scoped_tool, get_tools_by_names


async def get_agent_manager(session_context: SessionContext, memory: BaseMemory):
    """Create and configure the issue workflow management agent."""
    tools = await session_context.get_tools()

    try:
        tools = await get_tools_by_names(tools, ["create_issue", "list_issue_types"])

        create_issue = None
        list_issue_types = None

        for tool in tools:
            if tool.name == "create_issue":
                create_issue = await create_repo_scoped_tool(tool, session_context.get_repository())
            elif tool.name == "list_issue_types":
                list_issue_types = await create_repo_scoped_tool(tool, session_context.get_repository())

    except ToolNotFoundError as e:
        raise RuntimeError(f"Failed to configure the agent: {e}") from e

    # Get issue types with fallback
    fallback_types = [
        {"name": "Feature", "description": "A request, idea, or new functionality."},
        {"name": "Bug", "description": "An unexpected problem or behavior"},
    ]

    try:
        response = await list_issue_types.run(input={})
        issue_types_data = json.loads(response) if response else fallback_types
    except Exception:
        # Fallback to default types on any error (including 404)
        issue_types_data = fallback_types

    issue_types_lines = [f"- {issue_type['name']}: {issue_type['description']}" for issue_type in issue_types_data]
    issue_types_text = indent("\n".join(issue_types_lines), "    ")

    role = "helpful coordinator"
    instruction = f"""\
As the Coordinator, your responsibilities include routing tasks to experts, managing processes sequentially, and handling all user-facing communication. You do not perform technical writing or reasoning yourself.

You work in the following repository: {session_context.get_repository()}

## Operating Principles
- Manage the full lifecycle of a GitHub issue from user request to creation.
- Keep the user in control; never move forward without explicit consent.
- Communicate with the user only when a phase is complete or when experts request clarifications.
- Do not dispatch placeholder or deferred instructions (e.g., “HOLD”, “wait until approval”, “queue this”). Only issue tool calls that can execute immediately in the current phase.

## Phases

### 1. Draft
- Action: call `transfer_to_writer`.
- Do not add, expand, interpret, or restructure the user’s request yourself.
- If the writer asks for clarification, relay the question verbatim to the user.
- Relay policy for drafts:
    - Return the writer's draft to the user **exactly as received**.
    - Place your questions/notes **outside** the fence.

### 2. Review / Approval
- Action: call `final_answer` to share the draft exactly as received and ask: "Approve as-is, or request changes?"
- If changes are requested, return to **Draft**.
- Treat any of these as explicit approval: “approve”, “approved”, “looks good”, “LGTM”, “ship it”, “create it”, “go ahead”, “proceed”, “yes, create”.

### 3. Duplicate Check
- After approval, call `transfer_to_analyst` to search for similar issues.
- If duplicates found: let user decide to stop or continue.
- If unclear: ask user for refined search terms.

### 4. Create
- Only after explicit user confirmation, call `create_issue`.
- When creating the issue:
    - Use the first line inside the fenced block ([Feature]: ..., [Bug]: ..., etc.) as the issue title.
    - Remove that first line from the body so it does not appear twice.
    - Keep the remaining markdown inside the body exactly as written (do not expand, reformat, or add text).
- Select appropriate type from available issue types:
{issue_types_text}
- Then send brief confirmation with link/ID via `final_answer`.

## Output Rules
- Tone: professional, neutral, concise, and actionable.

## Reasoning Discipline
- Do not summarize, expand, or rewrite expert output.
- Do not anticipate clarifications yourself. Relay them only if explicitly requested by an expert.
- If the next step is to communicate with the user, **call `final_answer` now** (do not call other tools or pre-stage future work).

## Guardrails
- It is acceptable to remain in a phase across multiple messages until ready to proceed.
- Attempt a first pass autonomously unless critical input is missing; if so, stop and request clarification before proceeding.
"""

    # Get the specialized agents
    writer = await get_agent_writer(session_context)
    analyst = await get_agent_analyst(session_context)

    handoff_writer = HandoffTool(
        target=writer,
        name="transfer_to_writer",
        description="Assign to Technical Writer for drafting.",
        propagate_inputs=False,
    )

    handoff_analyst = HandoffTool(
        target=analyst,
        name="transfer_to_analyst",
        description="Assign to Analyst for duplicate issue search.",
        propagate_inputs=False,
    )

    template = dedent(
        """\
        # Role
        Assume the role of {{role}}.

        # Instructions
        {{#instructions}}
        {{&.}}
        {{/instructions}}
        {{#final_answer_schema}}
        The final answer must fulfill the following.

        ```
        {{&final_answer_schema}}
        ```
        {{/final_answer_schema}}
        {{#final_answer_instructions}}
        {{&final_answer_instructions}}
        {{/final_answer_instructions}}

        IMPORTANT: The facts mentioned in the final answer must be backed by evidence provided by relevant tool outputs.

        # Tools
        Never use the tool twice with the same input if not stated otherwise.

        {{#tools.0}}
        {{#tools}}
        Name: {{name}}
        Description: {{description}}

        {{/tools}}
        {{/tools.0}}

        {{#notes}}
        {{&.}}
        {{/notes}}
        """,
    )

    return RequirementAgent(
        name="Project Manager",
        llm=session_context.get_llm(),
        role=role,
        memory=memory,
        instructions=instruction,
        tools=[
            SimpleThinkTool(),
            handoff_writer,
            handoff_analyst,
            create_issue,
        ],
        requirements=[
            ConditionalRequirement(SimpleThinkTool, force_at_step=1, force_after=[Tool], consecutive_allowed=False),
            # AskPermissionRequirement(create_issue),
        ],
        templates={
            "system": PromptTemplate(PromptTemplateInput(schema=RequirementAgentSystemPromptInput, template=template)),
            # "task": PromptTemplate(PromptTemplateInput(schema=RequirementAgentTaskPromptInput, template="{{prompt}}")),
        },
        save_intermediate_steps=False,
        middlewares=[GlobalTrajectoryMiddleware(included=[Tool])],
    )
