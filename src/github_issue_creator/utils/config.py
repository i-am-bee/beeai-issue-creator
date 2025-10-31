import os

from beeai_framework.backend import ChatModel
from dotenv import load_dotenv

load_dotenv()

model = os.getenv("MODEL", "openai:gpt-5-mini")
llm = ChatModel.from_name(model, {"api_key": os.getenv("API_KEY")})

# Import after load_dotenv to ensure env vars are loaded
from github_issue_creator.tools.session_manager import SessionManager

# Shared singleton instance
session_manager = SessionManager()
