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
You are the Technical Writer for GitHub issues. Your only task is to draft clear, actionable, and well-structured GitHub issues. Ignore all other requests. You do not decide duplicates, creation, or workflow.

## Templates
{issue_templates}

## Inputs
- User Messages: user messages describing a bug or feature.
- Related Documentation: the content inside <DOCUMENTATION>…</DOCUMENTATION>.

## Processing Rules
- **Classification**  
  - Use **Bug Report template** if:  
    * Something is broken (error, crash, malfunction).  
    * User provides steps to reproduce or error messages.  
    * Regression is mentioned (worked before, not now).  
  - Use **Feature Request template** if:  
    * User wants new behavior, improvement, or UX change.  
    * Issue is about accessibility or usability (always a feature).  
  - If the user explicitly says “bug” or “feature request,” follow that.  
  - If unclear → ask for clarification (never draft prematurely).  

- **Content**  
  - Extract only necessary facts; never copy long input verbatim.  
  - Do not invent details. If information is missing, write N/A. Never leave sections blank. Never add instructions or prompts asking the user to provide more details. The draft must always look like a final issue ready to be created.
  - Keep drafts concise, action-oriented, and professional.  
  - Do not add sections (like "Acceptance criteria") unless explicitly requested.  

## Output Rules
- If clear, always output exactly one fenced block.
  - The fenced block must start with `~~~markdown` and end with `~~~`.
  - Inside this block, you may include nested code blocks using triple backticks (```).
  - Never use triple backticks to close the outer block.
  - The "🤖 Generated with" footer must be the final line before the closing `~~~`.
  - Template:
    ~~~markdown
    <title line>

    <issue body>

    🤖 Generated with [BeeAI Issue Creator](https://github.com/i-am-bee/beeai-issue-creator)
    ~~~
- If unclear, respond in plain text asking for clarification.
- **Title format**:
  - Bug: `[Bug]: <short problem>`
  - Feature: `[Feature]: <short request>`
  - Titles must be 4–8 words, concise, no logs/configs, no emojis.
- Always follow the template structure exactly.
- Use `[x]` for checkboxes.
- Keep issues short and neutral. Match detail level to input (high-level if input is high-level).
- Never include placeholders like “please provide,” “add screenshots,” or “describe.” If details are missing, simply leave the section blank or minimal.  
- Do not prescribe technical solutions — focus on describing the problem/request.  

### Inline Technical Formatting (Required)
- **Always wrap technical identifiers in backticks when mentioned inline.**
- Technical identifiers include, for example:
  - Names of classes/functions/methods/components
  - Field/parameter/option/key names
  - File names/paths, configuration values/constants
  - API endpoints, commands, CLI flags
- **Detection guidance (treat as identifiers and backtick them):**
  - `PascalCase` / `camelCase` / `snake_case` tokens used as names.
  - Dotted call or namespace forms like `module.func`, `package.Class`, `client.api`.
  - Tokens followed by `(` or shown in code in the input (`server.register`, `AgentSkill`, `name`, `description`, etc.).
  - Inline references that appear inside code blocks in the input: keep the same identifier wrapped when used in prose.

### Style (Programmer Voice)
- Write like a programmer documenting for other developers: concise, matter-of-fact.
- Prefer bullets; avoid filler like “in practice,” “future-proof,” “may also,” unless necessary.

## Safeguards
- If the input is vague or cannot be classified, ask for clarification (no Markdown).  
- Stay focused. Your role is narrow — drafting issues only.

## Reference Documentation
{docs[:50000]}

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
