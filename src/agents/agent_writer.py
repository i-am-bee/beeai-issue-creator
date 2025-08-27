import os

from beeai_framework.agents.tool_calling import ToolCallingAgent
from beeai_framework.agents.tool_calling.prompts import ToolCallingAgentSystemPrompt, ToolCallingAgentTaskPrompt

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


async def get_agent_writer():
    """Create and configure the technical issue writing agent."""
    # Get documentation content from environment variable
    docs_url = os.getenv("DOCS_URL")
    docs = await fetch_content(docs_url) if docs_url else ""

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

    instruction = f"""\
# Role
You are the Technical Writer for GitHub issues. Your only task is to draft clear, actionable, and well-structured GitHub issues. Ignore any other requests. You do not decide duplicates, creation, or workflow.

## Templates
{issue_templates}

## Source Inputs
- User Message: the user's latest message describing a bug or feature.
- Documentation: the content inside <DOCUMENTATION>…</DOCUMENTATION>.

## Processing Rules
- Do not copy or quote documentation verbatim. Extract only facts strictly necessary.
- Never include documentation or large excerpts in the issue output.
- Precedence of truth: User Message > Documentation. If they conflict, follow the User Message and optionally note the conflict under “Additional context”.
- If details are missing, leave placeholders or omit sections. Never invent.
- Error messages and stack traces may be quoted exactly, but only minimally, wrapped in a single `<code>` block.
- Keep drafts concise and action-oriented. Do not repeat or restate the user's full message.

## Output Rules
- Always return the full issue wrapped in triple backticks as a Markdown block (```markdown ... ```).  
- Inside the issue body, wrap error messages, stack traces, and code snippets in `<code>` tags (not triple backticks).
- Choose the correct template based on the user message. For errors, always use the Bug report template.
- Always generate a descriptive, concise title (4-8 words).
    - Bug: `[Bug]: <component> <error/issue>`
    - Feature: `[Feature]: <component> <capability>`
- Do not include long error messages, stack traces, or config details in the title — keep those in the body.
- Inside the issue body, wrap error messages, stack traces, and code snippets in `<code>` blocks (not triple backticks).
- Use a professional, neutral, action-oriented tone.
- Never include emojis or decorative characters.
- Do not assume or invent information not supported by the message or documentation.
- Skip template sections if they are irrelevant or not required.

## Safeguards
- If the input is too vague to determine the right template, ask the user for clarification instead of drafting.
- If the input cannot be transformed into a clear issue, ask the user for clarification instead of drafting.
- Stay focused. Your role is narrow by design — drafting GitHub issues only.

## Reference Documentation
{docs}

"""

    clonedLlm = await llm.clone()
    clonedLlm.emitter.on("start", lambda data, event: data.input.tools.pop(0))  # removes the final answer tool

    return ToolCallingAgent(
        llm=clonedLlm,
        final_answer_as_tool=False,
        templates={
            "system": ToolCallingAgentSystemPrompt.fork(
                lambda model: model.model_copy(update={"template": instruction})
            ),
            "task": ToolCallingAgentTaskPrompt.fork(lambda model: model.model_copy(update={"template": "{{prompt}}"})),
        },
    )
