import os

from dotenv import load_dotenv
from openinference.instrumentation.beeai import BeeAIInstrumentor

from agents.agent_draft_issue import draft_issue  # noqa: F401
from agents.agent_find_duplicates import find_duplicates  # noqa: F401
from agents.agent_orchestrate import orchestrate  # noqa: F401
from agents.server_instance import server

BeeAIInstrumentor().instrument()

load_dotenv()


def run():
    server.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 8000)),
        configure_telemetry=True,
    ) 


if __name__ == "__main__":
    run()
