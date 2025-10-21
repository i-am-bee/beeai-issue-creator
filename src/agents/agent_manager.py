import json
import os
from textwrap import dedent, indent

from beeai_framework.agents.experimental import RequirementAgent
from beeai_framework.agents.experimental.prompts import (
    RequirementAgentSystemPromptInput,
    RequirementAgentTaskPromptInput,
)
from beeai_framework.agents.experimental.requirements.ask_permission import AskPermissionRequirement
from beeai_framework.agents.experimental.requirements.conditional import ConditionalRequirement
from beeai_framework.middleware.trajectory import GlobalTrajectoryMiddleware
from beeai_framework.template import PromptTemplate, PromptTemplateInput
from beeai_framework.tools import Tool
from beeai_framework.tools.handoff import HandoffTool

from agents.agent_analyst import get_agent_analyst
from agents.agent_writer import get_agent_writer
from agents.artifact_handoff import ArtifactHandoffTool, ArtifactStore
from agents.artifact_middleware import ArtifactMiddleware
from agents.simple_think import SimpleThinkTool
from agents.utils import ToolNotFoundError, create_repo_scoped_tool, get_tools_by_names, llm, session_manager


async def get_agent_manager():
    """Create and configure the issue workflow management agent."""
    tools = await session_manager.get_tools()

    try:
        tools = await get_tools_by_names(tools, ["create_issue", "list_issue_types", "list_label"])

        create_issue = None
        list_issue_types = None
        list_label = None

        for tool in tools:
            if tool.name == "create_issue":
                create_issue = await create_repo_scoped_tool(tool)
            elif tool.name == "list_issue_types":
                list_issue_types = await create_repo_scoped_tool(tool)
            elif tool.name == "list_label":
                list_label = await create_repo_scoped_tool(tool)

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

    # Get labels with fallback
    fallback_labels = []

    try:
        response = await list_label.run(input={})
        # Parse nested response structure
        response_data = json.loads(response.get_text_content())
        # Extract text from first content block
        text_content = response_data[0]["text"]
        # Parse the JSON string inside
        labels_response = json.loads(text_content)
        # Extract labels array
        labels_data = labels_response["labels"]
    except Exception:
        # Fallback to empty list on any error (including 404, parsing errors)
        labels_data = fallback_labels

    # Extract only name and description from each label
    labels_lines = [f"- {label['name']}: {label.get('description', '')}" for label in labels_data]
    labels_text = indent("\n".join(labels_lines), "    ")

    repository = os.getenv("GITHUB_REPOSITORY")

    role = "helpful coordinator"
    instruction = f"""\
As the Coordinator, your responsibilities include routing tasks to experts, managing processes sequentially, and handling all user-facing communication. You do not perform technical writing or reasoning yourself.

You work in the following repository: {repository}

## Operating Principles
- Manage the full lifecycle of a GitHub issue from user request to creation.
- Keep the user in control; never move forward without explicit consent.
- Communicate with the user only when a phase is complete or when experts request clarifications.
- Do not dispatch placeholder or deferred instructions (e.g., "HOLD", "wait until approval", "queue this"). Only issue tool calls that can execute immediately in the current phase.

## Working with Artifacts
- Experts may return artifact references like `<artifact id="draft_k3x9" />` containing large content (drafts, etc.).
- Artifacts are **immutable**—they cannot be modified, only replaced by creating a new one.
- To show the full content to the user: include the artifact tag in your `final_answer` (it will auto-expand).
- To request changes: pass the artifact tag back to an expert along with change instructions (they see the full content and create a new artifact).
- Never create artifact tags yourself—only use what experts return.

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
- Select appropriate labels from available labels:
{labels_text}
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

    # Create shared artifact store
    artifact_store = ArtifactStore()

    # Get the specialized agents
    writer = await get_agent_writer()
    analyst = await get_agent_analyst()

    # Use artifact handoff for writer (drafts can be large)
    handoff_writer = ArtifactHandoffTool(
        target=writer,
        artifact_store=artifact_store,
        name="transfer_to_writer",
        description="Assign to Technical Writer for drafting.",
        propagate_inputs=False,
    )

    # Analyst needs full draft to search for duplicates
    handoff_analyst = ArtifactHandoffTool(
        target=analyst,
        artifact_store=artifact_store,
        name="transfer_to_analyst",
        description="Assign to Analyst for duplicate issue search.",
        propagate_inputs=False,
        reveal_policy="full",  # Analyst sees full draft content
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
        llm=llm,
        role=role,
        instructions=instruction,
        tools=[
            SimpleThinkTool(),
            handoff_writer,
            handoff_analyst,
            create_issue,
        ],
        requirements=[
            ConditionalRequirement(SimpleThinkTool, force_at_step=1, force_after=[Tool], consecutive_allowed=False),
            AskPermissionRequirement(create_issue),
        ],
        templates={
            "system": PromptTemplate(PromptTemplateInput(schema=RequirementAgentSystemPromptInput, template=template)),
            # "task": PromptTemplate(PromptTemplateInput(schema=RequirementAgentTaskPromptInput, template="{{prompt}}")),
        },
        save_intermediate_steps=False,
        middlewares=[
            ArtifactMiddleware(artifact_store),
            GlobalTrajectoryMiddleware(included=[Tool]),
        ],
    )
