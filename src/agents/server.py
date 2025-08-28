import asyncio
from textwrap import dedent

from a2a.types import AgentSkill
from beeai_framework.adapters.beeai_platform.serve.server import BeeAIPlatformServer
from beeai_sdk.a2a.extensions.ui.agent_detail import AgentDetail
from dotenv import load_dotenv
from openinference.instrumentation.beeai import BeeAIInstrumentor

from agents.agent_manager import get_agent_manager

BeeAIInstrumentor().instrument()


load_dotenv()


async def run():
    manager = await get_agent_manager()
    server = BeeAIPlatformServer(config={"configure_telemetry": True})
    server.register(
        manager,
        name="GitHub Issue Creator",
        description=dedent(
            """\
            Creates well-structured, actionable GitHub issues from user descriptions of bugs or feature requests.
            Uses project documentation and templates to ensure consistency and completeness.
            """
        ),
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
    )
    await server.aserve()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
