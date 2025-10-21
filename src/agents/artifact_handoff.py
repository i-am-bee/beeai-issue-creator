# Copyright 2025 © BeeAI a Series of LF Projects, LLC
# SPDX-License-Identifier: Apache-2.0

import random
import re
import string
from functools import cached_property
from typing import Any, Literal

from pydantic import BaseModel, Field

from beeai_framework.agents import BaseAgent
from beeai_framework.backend import AnyMessage, AssistantMessage, SystemMessage, UserMessage
from beeai_framework.context import RunContext
from beeai_framework.emitter import Emitter
from beeai_framework.memory import BaseMemory
from beeai_framework.runnable import Runnable
from beeai_framework.tools import StringToolOutput, Tool, ToolError, ToolRunOptions
from beeai_framework.utils.cloneable import Cloneable
from beeai_framework.utils.lists import find_index


class ArtifactStore:
    """Simple in-memory key-value store for artifacts"""

    def __init__(self):
        self._store: dict[str, dict[str, Any]] = {}

    def set(self, artifact_id: str, content: str, summary: str, created_by: str) -> None:
        """Store an artifact"""
        self._store[artifact_id] = {
            "content": content,
            "summary": summary,
            "created_by": created_by,
        }

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        """Retrieve an artifact"""
        return self._store.get(artifact_id)

    def has(self, artifact_id: str) -> bool:
        """Check if artifact exists"""
        return artifact_id in self._store

    def clear(self) -> None:
        """Clear all artifacts"""
        self._store.clear()


class HandoffSchema(BaseModel):
    task: str = Field(description="Clearly defined task for the agent to work on based on his abilities.")


class ArtifactHandoffTool(Tool[HandoffSchema, ToolRunOptions, StringToolOutput]):
    """Delegates a task to an expert agent with artifact management support"""

    def __init__(
        self,
        target: Runnable[Any],
        artifact_store: ArtifactStore,
        *,
        name: str | None = None,
        description: str | None = None,
        propagate_inputs: bool = True,
        reveal_policy: Literal["summary", "full"] = "summary",
    ) -> None:
        """Delegates a task to a specified expert agent with artifact handling.

        Args:
            target: The agent that will handle the delegated task.
            artifact_store: Shared artifact store for managing large content.
            name: Custom tool name. Defaults to the target's metadata name.
            description: Custom tool description. Defaults to the target's metadata description.
            propagate_inputs: Passes the tool's input to the target agent as the user input.
            reveal_policy: Controls what the target agent sees in message history:
                - "summary": Artifacts remain as references (default)
                - "full": Artifact references are expanded to full content

        Note: Artifacts are always stored with summary in the calling agent's history.
        """
        super().__init__()
        self._target = target
        self._artifact_store = artifact_store
        self._reveal_policy = reveal_policy

        if isinstance(target, BaseAgent):
            self._name = name or target.meta.name
            self._description = description or target.meta.description
        else:
            self._name = name or target.__class__.__name__
            self._description = description or (target.__class__.__doc__ or "")
        self._propagate_inputs = propagate_inputs

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @cached_property
    def input_schema(self) -> type[HandoffSchema]:
        return HandoffSchema

    async def _run(self, input: HandoffSchema, options: ToolRunOptions | None, context: RunContext) -> StringToolOutput:
        memory: BaseMemory = context.context["state"]["memory"]
        if not memory or not isinstance(memory, BaseMemory):
            raise ToolError("No memory found in context.")

        target: Runnable[Any] = await self._target.clone() if isinstance(self._target, Cloneable) else self._target

        non_system_messages = [msg for msg in memory.messages if not isinstance(msg, SystemMessage)]
        last_valid_msg_index = find_index(
            non_system_messages,
            lambda msg: not isinstance(msg, AssistantMessage) or not msg.get_tool_calls(),
            reverse_traversal=True,
            fallback=-1,
        )

        # Get messages to pass to target agent
        messages_to_pass = non_system_messages[: last_valid_msg_index + 1]

        # Apply reveal policy to messages
        if self._reveal_policy == "full":
            messages_to_pass = self._reveal_artifacts(messages_to_pass)

        messages: list[AnyMessage] = []
        if isinstance(target, BaseAgent):
            target.memory.reset()
            await target.memory.add_many(messages_to_pass)
        else:
            messages = messages_to_pass

        if self._propagate_inputs:
            messages.append(UserMessage(content=input.task))

        response = await target.run(messages)
        response_text = response.last_message.text

        # Try to parse as artifact
        artifact = self._parse_artifact(response_text)

        if artifact:
            # Generate random ID (e.g., "draft_k3x9")
            artifact_id = self._generate_artifact_id()

            # Store in artifact store
            self._artifact_store.set(
                artifact_id=artifact_id,
                content=artifact["content"],
                summary=artifact["summary"],
                created_by=self._name,
            )

            # Always return artifact reference with summary
            return StringToolOutput(
                f'<artifact id="{artifact_id}" summary="{artifact["summary"]}" />'
            )

        # Not an artifact, return as-is
        return StringToolOutput(response_text)

    def _generate_artifact_id(self) -> str:
        """Generate a short random artifact ID like 'draft_k3x9'"""
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        return f"draft_{suffix}"

    def _reveal_artifacts(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """Replace artifact references with full content in messages."""
        revealed = []
        for msg in messages:
            content = msg.text if hasattr(msg, 'text') else str(msg.content)
            # Simple regex to find <artifact id="..." /> and replace with content
            new_content = re.sub(
                r'<artifact id="([^"]+)"[^>]*/>',
                lambda m: self._artifact_store.get(m.group(1), {}).get("content", m.group(0)),
                content
            )
            if new_content != content:
                if isinstance(msg, UserMessage):
                    revealed.append(UserMessage(content=new_content))
                elif isinstance(msg, AssistantMessage):
                    revealed.append(AssistantMessage(content=new_content))
                else:
                    revealed.append(msg)
            else:
                revealed.append(msg)
        return revealed

    def _parse_artifact(self, text: str) -> dict[str, str] | None:
        """Parse artifact format from agent response.

        Expected format:
        ARTIFACT
        ARTIFACT_SUMMARY: Brief description

        {content}

        Returns:
            Dict with 'summary' and 'content' keys, or None if not an artifact
        """
        text = text.strip()

        # Check if starts with ARTIFACT marker
        if not text.startswith("ARTIFACT"):
            return None

        # Split into lines
        lines = text.split('\n')

        # Find ARTIFACT_SUMMARY line
        summary_line_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith("ARTIFACT_SUMMARY:"):
                summary_line_idx = i
                break

        if summary_line_idx is None:
            return None

        # Extract summary
        summary = lines[summary_line_idx].replace("ARTIFACT_SUMMARY:", "").strip()

        # Everything after the summary line is content
        content_lines = []
        for i in range(summary_line_idx + 1, len(lines)):
            content_lines.append(lines[i])

        content = '\n'.join(content_lines).strip()

        if not content:
            return None

        return {
            "summary": summary,
            "content": content,
        }

    def _create_emitter(self) -> Emitter:
        return Emitter.root().child(
            namespace=["tool", "artifact_handoff"],
            creator=self,
        )
