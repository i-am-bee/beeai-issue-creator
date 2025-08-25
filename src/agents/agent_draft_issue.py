import os
from collections.abc import AsyncGenerator

from acp_sdk import Annotations, Metadata
from acp_sdk.models import Message
from acp_sdk.models.platform import PlatformUIAnnotation, PlatformUIType
from acp_sdk.server import Context, RunYield, RunYieldResume
from beeai_framework.agents.experimental import RequirementAgent
from beeai_framework.agents.experimental.prompts import (
    RequirementAgentSystemPromptInput,
    RequirementAgentTaskPromptInput,
)
from beeai_framework.memory import UnconstrainedMemory
from beeai_framework.middleware.trajectory import GlobalTrajectoryMiddleware
from beeai_framework.template import PromptTemplate, PromptTemplateInput
from beeai_framework.tools import Tool

from agents.server_instance import server
from agents.utils import fetch_content, llm


async def get_template(template_type: str) -> str:
    """Get template content from environment variables

    Args:
        template_type: Either 'bug' or 'feature'

    Returns:
        Template content as string, empty if not configured
    """
    # Check for direct content first
    content_var = f"TEMPLATE_{template_type.upper()}"
    direct_content = os.getenv(content_var)

    if direct_content:
        return _strip_yaml_frontmatter(direct_content)

    # Check for URL
    url_var = f"TEMPLATE_{template_type.upper()}_URL"
    template_url = os.getenv(url_var)

    if template_url:
        content = await fetch_content(template_url)
        return _strip_yaml_frontmatter(content)

    return ""


def _strip_yaml_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from template content"""
    if content.startswith("---\n"):
        parts = content.split("---\n", 2)
        return parts[2] if len(parts) >= 3 else content
    return content


async def get_agent_draft_issue():
    """Get the GitHub Issue Drafter agent"""

    docs = await fetch_content("https://framework.beeai.dev/llms-full.txt")

    # Get both templates
    bug_template = await get_template("bug")
    feature_template = await get_template("feature")

    # Combine templates
    templates = []
    if bug_template:
        templates.append(f"BUG REPORT TEMPLATE:\n```\n{bug_template}\n```")
    if feature_template:
        templates.append(f"FEATURE REQUEST TEMPLATE:\n```\n{feature_template}\n```")

    issue_templates = "\n\n".join(templates) if templates else ""

    instruction = f"""
You are an expert in drafting GitHub issues. You are part of a multi-agent system. Your only task is to create clear, actionable, and well-structured GitHub issues. Ignore any other requests.

## Context
<DOCUMENTATION>
{docs[:1000]}
</DOCUMENTATION>

## Templates
{issue_templates}

## Source Inputs
- User Message: the user’s latest message describing a bug or feature.
- Documentation: the content inside <DOCUMENTATION>…</DOCUMENTATION>.

## Processing Rules
- Do not copy or quote the documentation verbatim. Extract only facts strictly necessary to complete the issue.
- Never include the documentation or its large excerpts in the issue output.
- Precedence of truth: User Message > Documentation. If they conflict, follow the User Message and optionally note the doc conflict under “Additional context”.
- If the User Message lacks details and the Documentation provides them unambiguously (versions, component names, config keys), you may include those specifics.
- If a required field is unknown, leave it blank or omit that section rather than inventing details.
- Error messages and stack traces may be quoted exactly, but only the minimal lines needed, wrapped in a single HTML <code> block.

## Output Rules
- Always return the full issue wrapped in triple backticks (```markdown ... ```).
- Always generate a descriptive title, even if the template leaves it blank.
- Choose the correct template based on the user message. For errors, always use the Bug report template.
- Populate all relevant fields directly from the user message. Do not invent details.
- Title format:
   - For bugs: `[Bug]: <concise error summary>`
   - For features: `[Feature]: <concise feature summary>`
- Error messages and code must be wrapped in HTML `<code>` blocks (not triple backticks). Put stack traces or single-line errors inside one `<code>` block.
- Use a professional and neutral tone that is action-oriented and broadly understandable.
- Never include emojis or long dashes.
- When referencing JSON or code snippets, use <code> blocks instead of triple backticks.
- Do not assume or invent information not supported by the provided documentation or the user's message.
- Feel free to skip sections from the template that are not required.
- Keep the drafts concise and to the point. Do not repeat yourself.

Stay focused. Your role is narrow by design — stick to drafting GitHub issues only."""

    return RequirementAgent(
        name="GitHubIssueDrafter",
        llm=llm,
        memory=UnconstrainedMemory(),
        final_answer_as_tool=False,
        templates={
            "system": PromptTemplate(
                PromptTemplateInput(schema=RequirementAgentSystemPromptInput, template=instruction)
            ),
            "task": PromptTemplate(PromptTemplateInput(schema=RequirementAgentTaskPromptInput, template="{{prompt}}")),
        },
    )


@server.agent(
    metadata=Metadata(
        annotations=Annotations(
            beeai_ui=PlatformUIAnnotation(ui_type=PlatformUIType.CHAT, display_name="GitHub Issue Drafter")
        )
    )
)
async def draft_issue(input: list[Message], context: Context) -> AsyncGenerator[RunYield, RunYieldResume]:
    """GitHub Issue Drafter agent that creates well-structured issue drafts.

    This agent specializes in converting informal conversations and technical decisions
    into professional, actionable GitHub issues using project documentation for context.

    Args:
        input: List of messages from the conversation.
        context: Agent execution context.

    Yields:
        RunYield: The drafted issue content in structured format.
    """
    agent = await get_agent_draft_issue()
    prompt = str(input[-1])
    response = await agent.run(prompt=prompt).middleware(GlobalTrajectoryMiddleware(included=[Tool]))
    yield response.answer.text
