# Copyright 2025 © BeeAI a Series of LF Projects, LLC
# SPDX-License-Identifier: Apache-2.0

import re

from beeai_framework.agents import BaseAgent
from beeai_framework.agents.requirement.utils._tool import FinalAnswerTool
from beeai_framework.backend import MessageTextContent
from beeai_framework.context import RunContext, RunMiddlewareProtocol
from beeai_framework.emitter import EmitterOptions, EventMeta

from agents.artifact_handoff import ArtifactStore


class ArtifactMiddleware(RunMiddlewareProtocol):
    """Middleware that expands artifact references in final answers"""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._artifact_store = artifact_store

    def bind(self, run: RunContext) -> None:
        agent = run.instance
        assert isinstance(agent, BaseAgent), "Input must be an agent"

        run.emitter.on(
            lambda event: event.name == "success" and isinstance(event.creator, FinalAnswerTool),
            self._handle_final_answer,
            EmitterOptions(match_nested=True, is_blocking=True, priority=2),
        )

    async def _handle_final_answer(self, data, meta: EventMeta) -> None:
        # Get the FinalAnswerTool instance from the event creator
        tool = meta.creator
        if not isinstance(tool, FinalAnswerTool):
            return

        # Get the message from the tool's state
        message = tool._state.answer
        if not message:
            return

        # Expand artifacts in all text chunks
        for chunk in message.content:
            if isinstance(chunk, MessageTextContent):
                expanded_text = self._expand_artifacts(chunk.text)
                if expanded_text != chunk.text:
                    chunk.text = expanded_text

    def _expand_artifacts(self, text: str) -> str:
        """Replace artifact references with full content"""
        # Pattern matches: <artifact id="draft_k3x9" /> or <artifact id="draft_k3x9" summary="..." />
        pattern = r'<artifact\s+id="([^"]+)"(?:\s+summary="[^"]*")?\s*/>'

        def replace_artifact(match):
            artifact_id = match.group(1)
            artifact_data = self._artifact_store.get(artifact_id)
            return artifact_data["content"] if artifact_data else match.group(0)

        return re.sub(pattern, replace_artifact, text)
