import asyncio
import os
from textwrap import dedent
from typing import Annotated

from beeai_framework.backend import AssistantMessage, UserMessage
from beeai_framework.memory.unconstrained_memory import UnconstrainedMemory
from beeai_sdk.a2a.extensions import (
    LLMServiceExtensionServer,
    LLMServiceExtensionSpec,
    SecretDemand,
    SecretsExtensionSpec,
)
from beeai_sdk.a2a.extensions.auth.secrets import SecretsExtensionServer, SecretsServiceExtensionParams
from beeai_sdk.a2a.extensions.ui.form import FormExtensionServer, FormExtensionSpec, FormRender, TextField
from beeai_sdk.server import Server
from a2a.utils.message import get_message_text

from a2a.types import AgentSkill, Message
from beeai_sdk.a2a.extensions.ui.agent_detail import AgentDetail
from beeai_sdk.server.context import RunContext
from beeai_sdk.server.store.platform_context_store import PlatformContextStore
from dotenv import load_dotenv
from openinference.instrumentation.beeai import BeeAIInstrumentor
import pydantic

from agents.agent_manager import get_agent_manager
from agents.session_context import SessionContext

BeeAIInstrumentor().instrument()


load_dotenv()


class InputFormModel(pydantic.BaseModel):
    repo: str
    docs_url: str
    bug_template_url: str
    feature_template_url: str


server = Server()

memories = {}
forms: dict[str, InputFormModel] = {}


async def extract_github_pat_secret(secrets: SecretsExtensionServer) -> str:
    if (
        secrets is None
        or secrets.data is None
        or secrets.data.secret_fulfillments is None
        or secrets.data.secret_fulfillments.get("default") is None
    ):
        dynamic_secrets = await secrets.request_secrets(
            params=SecretsServiceExtensionParams(
                secret_demands={"default": SecretDemand(description="Github Personal Access Token", name="Github PAT")}
            )
        )
        if dynamic_secrets is None:
            raise ValueError("No Github Personal Access Token found")

        return dynamic_secrets.secret_fulfillments["default"].secret
    else:
        return secrets.data.secret_fulfillments["default"].secret

def get_memory(context: RunContext) -> UnconstrainedMemory:
    """Get or create session memory"""
    context_id = getattr(context, "context_id", getattr(context, "session_id", "default"))
    return memories.setdefault(context_id, UnconstrainedMemory())


@server.agent(
    name="GitHub Issue Creator",
    description=dedent(
        """\
        Creates well-structured, actionable GitHub issues from user descriptions of bugs or feature requests.
        Uses project documentation and templates to ensure consistency and completeness.
        """
    ),
    detail=AgentDetail(
        default_input_modes=["text"],
        default_output_modes=["text"],
        detail=AgentDetail(
            interaction_mode="multi-turn",
            framework="BeeAI",
        ),
        skills=[
            AgentSkill(
                id="create_github_issue",
                name="Create GitHub Issue",
                description=dedent(
                    """\
                Creates well-structured, actionable GitHub issues from user descriptions of bugs or feature requests.
                Uses project documentation and templates to ensure consistency and completeness.
                """
                ),
                tags=["GitHub", "Issues", "Bug Reports", "Feature Requests", "Documentation"],
                examples=[
                    "The login form crashes when I enter special characters in the password field",
                    "Add support for dark mode theme in the user interface",
                    "API returns 500 error when making concurrent requests to /users endpoint",
                    "Implement user authentication with OAuth2 integration",
                    "Memory leak occurs after running the application for several hours",
                ],
            )
        ],
    ),
)
async def github_issue_creator(
    input: Message,
    context: RunContext,
    llm: Annotated[LLMServiceExtensionServer, LLMServiceExtensionSpec.single_demand()],
    secrets: Annotated[
        SecretsExtensionServer,
        SecretsExtensionSpec.single_demand(name="Github", description="Github Personal Access Token"),
    ],
    form: Annotated[
        FormExtensionServer,
        FormExtensionSpec(
            params=FormRender(
                id="initial_data",
                title="Let's file an issue together.",
                columns=2,
                fields=[
                    TextField(
                        id="repo", label="Github Repository", type="text", col_span=2, default_value="owner/repo"
                    ),
                    TextField(
                        id="docs_url",
                        label="Documentation URL",
                        type="text",
                        col_span=2,
                        auto_resize=True,
                        default_value="https://example.com/llms-full.txt",
                    ),
                    TextField(
                        id="bug_template_url",
                        label="Template for Bugs (URL)",
                        type="text",
                        col_span=2,
                        auto_resize=True,
                        default_value="https://raw.githubusercontent.com/user/repo/main/.github/ISSUE_TEMPLATE/bug_report.md",
                    ),
                    TextField(
                        id="feature_template_url",
                        label="Template for Features (URL)",
                        type="text",
                        col_span=2,
                        auto_resize=True,
                        default_value="https://raw.githubusercontent.com/user/repo/main/.github/ISSUE_TEMPLATE/feature_request.md",
                    ),
                ],
            )
        ),
    ],
):
    github_pat = await extract_github_pat_secret(secrets)

    try:
        parsed_form_data = form.parse_form_response(message=input)

        forms[context.context_id] = InputFormModel.model_validate(
            {
                "repo": parsed_form_data.values["repo"].value,
                "docs_url": parsed_form_data.values["docs_url"].value,
                "bug_template_url": parsed_form_data.values["bug_template_url"].value,
                "feature_template_url": parsed_form_data.values["feature_template_url"].value,
            }
        )

        yield "Lets provide the prompt now."
        return
    except Exception:
        pass


    parsed_form_data = forms[context.context_id]
    if not parsed_form_data:
        raise ValueError("No form data found")

    text_input = get_message_text(input)
    memory = get_memory(context)
    await memory.add(UserMessage(text_input))

    llm_config = llm.data.llm_fulfillments.get("default")
    if not llm_config:
        raise ValueError("No LLM config found")

    session_context = SessionContext(
        llm_config,
        github_pat,
        parsed_form_data.repo,
        parsed_form_data.docs_url,
        parsed_form_data.bug_template_url,
        parsed_form_data.feature_template_url,
    )
    await session_context.connect()

    manager = await get_agent_manager(session_context, memory)

    async for event, meta in manager.run(text_input):
        if meta.name == "success" and event.state.steps:
            step = event.state.steps[-1]
            if not step.tool:
                continue

            tool_name = step.tool.name
            if tool_name == "final_answer":
                response_text = step.input["response"]
                await memory.add(AssistantMessage(response_text))
                yield response_text


def run():
    server.run(
        host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", 8000)), context_store=PlatformContextStore()
    )


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
