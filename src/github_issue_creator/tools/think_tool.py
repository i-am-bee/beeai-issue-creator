from pydantic import BaseModel, Field

from beeai_framework.context import RunContext
from beeai_framework.emitter import Emitter
from beeai_framework.tools import StringToolOutput, Tool, ToolRunOptions


class ThinkSchema(BaseModel):
    thoughts: str = Field(
        ...,
        description="One concise internal sentence about the immediate next step. Do not include status updates, promises, or user-facing text.",
    )


class SimpleThinkTool(Tool[ThinkSchema]):
    name = "think"
    description = "Internal reasoning only. Use to state, in one concise sentence, the immediate next step (which tool/phase to use, or wait). No user-facing text, promises, or status updates."  # noqa: E501

    def __init__(self, *, extra_instructions: str = "") -> None:
        super().__init__()
        if extra_instructions:
            self.description += f" {extra_instructions}"

    @property
    def input_schema(self) -> type[ThinkSchema]:
        return ThinkSchema

    async def _run(self, input: ThinkSchema, options: ToolRunOptions | None, context: RunContext) -> StringToolOutput:
        return StringToolOutput("OK")

    def _create_emitter(self) -> Emitter:
        return Emitter.root().child(
            namespace=["tool", "think"],
            creator=self,
        )
