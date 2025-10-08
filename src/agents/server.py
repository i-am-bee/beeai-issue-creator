import asyncio
import os
from textwrap import dedent
from typing import Annotated

from beeai_framework.backend import AssistantMessage
from beeai_framework.memory.unconstrained_memory import UnconstrainedMemory
from beeai_sdk.a2a.extensions import (
    AgentDetailContributor,
    AgentDetailTool,
    LLMServiceExtensionServer,
    LLMServiceExtensionSpec,
    SecretDemand,
    SecretsExtensionSpec,
)
from beeai_sdk.a2a.extensions.auth.secrets import SecretsExtensionServer, SecretsServiceExtensionParams
from beeai_sdk.a2a.extensions.ui.form import FormExtensionServer, FormExtensionSpec, FormRender, TextField
from beeai_sdk.a2a.types import AgentMessage
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
from agents.utils import to_framework_message

BeeAIInstrumentor().instrument()


load_dotenv()


class InputFormModel(pydantic.BaseModel):
    repo: str
    docs_url: str
    bug_template_url: str
    feature_template_url: str


server = Server()


async def extract_github_pat_secret(secrets: SecretsExtensionServer) -> str:
    if (
        secrets is None
        or secrets.data is None
        or secrets.data.secret_fulfillments is None
        or secrets.data.secret_fulfillments.get("github") is None
    ):
        dynamic_secrets = await secrets.request_secrets(
            params=SecretsServiceExtensionParams(
                secret_demands={"github": SecretDemand(description="Github Personal Access Token", name="Github PAT")}
            )
        )
        if dynamic_secrets is None:
            raise ValueError("No Github Personal Access Token found")

        return dynamic_secrets.secret_fulfillments["github"].secret
    else:
        return secrets.data.secret_fulfillments["github"].secret


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
        interaction_mode="multi-turn",
        framework="BeeAI",
        author=AgentDetailContributor(name="Matous Havlena", email="matous.havlena@ibm.com"),
        tools=[
            AgentDetailTool(
                name="Github", description="Github integration allows to browse and create issues in the repository."
            )
        ],
        source_code_url="https://github.com/i-am-bee/beeai-issue-creator",
        container_image_url="ghcr.io/i-am-bee/beeai-issue-creator/beeai-issue-creator",
        skills=[
            AgentSkill(
                id="create_github_issue",
                name="Create GitHub Issue",
                description="Create a GitHub issue",
                tags=["GitHub", "Issues", "Bug Reports", "Feature Requests", "Documentation"],
            )
        ],
    ),
)
async def github_issue_creator(
    input: Message,
    context: RunContext,
    llm: Annotated[
        LLMServiceExtensionServer,
        LLMServiceExtensionSpec.single_demand(suggested=("openai:gpt-5-nano", "rits:meta-llama/llama4-maverick-17b-128e-instruct-fp8")),
    ],
    secrets: Annotated[
        SecretsExtensionServer,
        SecretsExtensionSpec(
            params=SecretsServiceExtensionParams(
                secret_demands={"github": SecretDemand(description="Github Personal Access Token", name="Github PAT")}
            )
        ),
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
    await context.store(input)
    history = [message async for message in context.load_history()]
    new_messages = [to_framework_message(item) for item in history]
    memory = UnconstrainedMemory()
    await memory.add_many(new_messages)

    github_pat = await extract_github_pat_secret(secrets)

    parsed_form_data = None
    for message in history:
        try:
            form_response = form.parse_form_response(message=message)
            parsed_form_data = InputFormModel.model_validate(
                {
                    "repo": form_response.values["repo"].value,
                    "docs_url": form_response.values["docs_url"].value,
                    "bug_template_url": form_response.values["bug_template_url"].value,
                    "feature_template_url": form_response.values["feature_template_url"].value,
                }
            )
            break
        except Exception:
            continue

    if parsed_form_data is None:
        raise ValueError("No form data found")

    text_input = get_message_text(input)

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

                msg = AgentMessage(text=response_text)
                await context.store(msg)
                yield msg


def run():
    server.run(
        host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", 8000)), context_store=PlatformContextStore()
    )


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
