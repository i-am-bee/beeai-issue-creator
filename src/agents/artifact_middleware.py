# Copyright 2025 © BeeAI a Series of LF Projects, LLC
# SPDX-License-Identifier: Apache-2.0

import re

from beeai_framework.agents import BaseAgent
from beeai_framework.backend import MessageTextContent
from beeai_framework.context import RunContext, RunContextSuccessEvent, RunMiddlewareProtocol
from beeai_framework.emitter import EmitterOptions, EventMeta
from beeai_framework.emitter.utils import create_internal_event_matcher

from agents.artifact_handoff import ArtifactStore


class ArtifactMiddleware(RunMiddlewareProtocol):
    """Middleware that expands artifact references in final answers.

    Note: Currently incomplete - needs to hook into the correct event to expand
    artifacts before the message is sent to the user.
    """

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._artifact_store = artifact_store

    def bind(self, run: RunContext) -> None:
        agent = run.instance
        assert isinstance(agent, BaseAgent), "Input must be an agent"

        # TODO: Find the correct way to hook into final_answer tool
        # The final_answer tool is not in agent.meta.tools for RequirementAgent
        # Need to find where it's added and hook into it before message is sent

    def _expand_artifacts(self, text: str) -> str:
        """Replace artifact references with full content"""
        pattern = r'<artifact\s+id="([^"]+)"(?:\s+summary="[^"]*")?\s*/>'

        def replace_artifact(match):
            artifact_id = match.group(1)
            artifact_data = self._artifact_store.get(artifact_id)

            if artifact_data:
                return artifact_data["content"]
            else:
                # Artifact not found, leave as-is
                return match.group(0)

        return re.sub(pattern, replace_artifact, text)
