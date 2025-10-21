# Artifact System Documentation

## Overview

The artifact system allows agents to store large content (like issue drafts) in a key-value store and pass lightweight references instead of full content in conversation history. This keeps the orchestrator agent's context clean while still allowing specialized agents to access full content when needed.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Manager Agent                            │
│  History: User request → <artifact id="draft_k3x9" summary=.../>│
└────────────┬────────────────────────────────────┬───────────────┘
             │                                     │
             │ transfer_to_writer                  │ transfer_to_analyst
             │ (reveal_policy: summary)            │ (reveal_policy: full)
             ↓                                     ↓
    ┌────────────────┐                    ┌────────────────────┐
    │  Writer Agent  │                    │   Analyst Agent    │
    │                │                    │                    │
    │ Generates:     │                    │ Sees full content: │
    │ ARTIFACT       │                    │ ~~~markdown        │
    │ ARTIFACT_      │                    │ [Feature]: ...     │
    │  SUMMARY: ...  │                    │ ...                │
    │                │                    │ ~~~                │
    │ ~~~markdown    │                    │                    │
    │ [Feature]: ... │                    └──────────┬─────────┘
    │ ...            │                               │
    │ ~~~            │                               │
    └────────┬───────┘                               │
             │                                       │
             └───────────────┬───────────────────────┘
                             │
                             ↓
                  ┌──────────────────────┐
                  │   ArtifactStore      │
                  │  {                   │
                  │   "draft_k3x9": {    │
                  │     content: "...",  │
                  │     summary: "...",  │
                  │     created_by: "..." │
                  │   }                  │
                  │  }                   │
                  └──────────────────────┘

Flow:
1. Manager → Writer: "Draft an issue for dark mode"
2. Writer generates ARTIFACT + content
3. ArtifactHandoffTool:
   - Parses artifact
   - Stores in ArtifactStore with random ID
   - Returns: <artifact id="draft_k3x9" summary="Add dark mode theme" />
4. Manager sees lightweight reference in history
5. Manager → Analyst: "Check for duplicates" + artifact reference
6. ArtifactHandoffTool (reveal_policy=full):
   - Expands artifact reference to full content
   - Analyst sees complete draft
7. [TODO] Manager → User: Should expand artifact in final answer
```

## Components

### 1. ArtifactStore (`artifact_handoff.py`)
Simple in-memory key-value store for artifacts.

### 2. ArtifactHandoffTool (`artifact_handoff.py`)
Enhanced handoff tool that automatically detects and stores artifacts from agent responses.

**How it works:**
- Agent generates content in special format:
  ```
  ARTIFACT
  ARTIFACT_SUMMARY: Brief description

  {large content here}
  ```
- Tool parses this, generates random ID (e.g., `draft_k3x9`), stores content
- Returns lightweight reference: `<artifact id="draft_k3x9" summary="Brief description" />`

**Reveal Policy:**
- `"summary"` (default): Target agent sees artifact references as-is
- `"full"`: Target agent sees full expanded content

### 3. ArtifactMiddleware (`artifact_middleware.py`)
**STATUS: INCOMPLETE**

Middleware intended to expand artifact references before final answer is sent to user.

**Current Issue:** Cannot find the `final_answer` tool to hook into. The RequirementAgent adds it automatically and it's not present in `agent.meta.tools`.

**What works:**
- `_expand_artifacts()` method correctly replaces `<artifact id="..." />` with full content from store
- Pattern matching works for both `<artifact id="x" />` and `<artifact id="x" summary="..." />`

**What doesn't work:**
- Cannot hook into the right event before message is sent to WebUI
- Need to find where `final_answer` tool is added in RequirementAgent and hook before it finishes

## Current Usage

### In agent_manager.py:
```python
artifact_store = ArtifactStore()

handoff_writer = ArtifactHandoffTool(
    target=writer,
    artifact_store=artifact_store,
    reveal_policy="summary",  # Manager sees only summary
)

handoff_analyst = ArtifactHandoffTool(
    target=analyst,
    artifact_store=artifact_store,
    reveal_policy="full",  # Analyst sees full content
)
```

### In agent_writer.py:
Writer agent instructed to output:
```
ARTIFACT
ARTIFACT_SUMMARY: Brief one-line description

~~~markdown
{draft content}
~~~
```

## TODO

1. **Fix ArtifactMiddleware** - Find correct event to hook into for expanding artifacts before final answer is sent
2. **Test end-to-end** - Verify artifacts are expanded in WebUI output
3. **Consider alternatives** - Maybe post-process output outside of middleware?

## Design Decisions

- **Immutable artifacts**: Once created, artifacts cannot be modified (only replaced)
- **Random IDs**: Using random 4-char suffix (e.g., `draft_k3x9`) to prevent LLMs from guessing IDs
- **Simple format**: ARTIFACT marker + ARTIFACT_SUMMARY + content for easy parsing
- **Hybrid syntax**: ARTIFACT for generation, XML-style `<artifact />` for references

## Notes

The middleware timing issue: WebUI logs show FinalAnswerTool finishing BEFORE middleware runs, so message is already sent before artifacts can be expanded.
