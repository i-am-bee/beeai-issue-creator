# BeeAI Issue Creator

A multi-agent system for creating well-structured GitHub issues using the [BeeAI Framework](https://framework.beeai.dev/experimental/requirement-agent). This system coordinates between specialized agents to draft issues, check for duplicates, and create final GitHub issues with customizable templates.

✅ Production-ready multi-agent workflow  
🔄 Real-time trajectory tracking  
📝 Customizable issue templates

## What is BeeAI Issue Creator?

The BeeAI Issue Creator orchestrates a multi-step workflow using specialized agents:

- **Orchestrator**: Coordinates the entire workflow and manages agent handoffs
- **Issue Drafter**: Creates structured issue drafts from user input using templates, grounded with project documentation for technical accuracy
- **Duplicate Finder**: Searches for existing similar issues to prevent duplicates

This gives you consistent, professional GitHub issues while preventing duplicates and maintaining quality standards. The system integrates with GitHub through the [GitHub MCP server](https://github.com/modelcontextprotocol/servers/tree/main/src/github) for seamless repository interactions.

## Use Cases

Perfect for:
- Automated issue creation from user reports
- Maintaining consistent issue formatting across repositories
- Preventing duplicate issues through intelligent search
- Multi-step workflows with user approval gates

## Agents Included

🎯 **[Orchestrator](src/agents/agent_orchestrate.py)** - Manages the complete issue lifecycle from draft to creation  
📝 **[Issue Drafter](src/agents/agent_draft_issue.py)** - Creates structured issues using customizable templates  
🔍 **[Duplicate Finder](src/agents/agent_find_duplicates.py)** - Searches for similar existing issues

## Features

- **Template Support**: Bug report and feature request templates
- **Documentation Grounding**: Issue Drafter uses project documentation for technical accuracy
- **GitHub Integration**: Seamless interaction through GitHub MCP server
- **Trajectory Tracking**: Real-time visibility into agent interactions and tool usage
- **Duplicate Prevention**: Intelligent search for existing similar issues
- **User Approval**: Human-in-the-loop workflow with approval gates
- **Conditional Requirements**: Enforced workflow steps and dependencies

## Quickstart

```bash
# Install dependencies
uv sync --group dev

# Copy and edit environment variables
cp .env.example .env
# Set your MODEL, API_KEY, GITHUB_PAT, and templates in .env

# Start the agent server
uv run server
```

The server will start on `http://127.0.0.1:8000` and register three agents:
- `orchestrate` - Main workflow coordinator
- `draft_issue` - Issue drafting specialist
- `find_duplicates` - Duplicate detection specialist

## Configuration

### Environment Variables

Configure the system using environment variables:

```bash
# Model Configuration
MODEL=openai:gpt-5-nano
API_KEY=your_api_key_here

# GitHub Configuration  
GITHUB_PAT=your_github_personal_access_token
GITHUB_REPOSITORY=owner/repository-name

# Documentation for issue grounding (optional)
DOCS_URL=https://example.com/llms-full.txt

# Issue Templates (URLs preferred)
TEMPLATE_BUG_URL="https://raw.githubusercontent.com/user/repo/main/.github/ISSUE_TEMPLATE/bug_report.md"
TEMPLATE_FEATURE_URL="https://raw.githubusercontent.com/user/repo/main/.github/ISSUE_TEMPLATE/feature_request.md"

# Alternative: Direct template content
TEMPLATE_BUG="your bug report template..."
TEMPLATE_FEATURE="your feature request template..."
```

### Template Format

Templates use standard Markdown format:

```markdown
**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

**Expected behavior**
A clear and concise description of what you expected to happen.
```

## Workflow

1. **User Input**: Describe the bug or feature request
2. **Draft Creation**: Issue Drafter creates structured draft using templates
3. **Duplicate Check**: Duplicate Finder searches for similar existing issues
4. **User Review**: User reviews and approves the draft
5. **Issue Creation**: Final GitHub issue is created with proper formatting

## Development

```bash
# Install development dependencies
uv sync --group dev

# Run linting
uv run ruff check

# Run formatting
uv run ruff format
```

## Architecture

The system uses the BeeAI Framework's Requirement Agent with:
- **Conditional Requirements**: Enforced workflow sequence
- **Handoff Tools**: Agent-to-agent delegation
- **Permission Requirements**: User approval gates
- **Trajectory Middleware**: Real-time progress tracking

## Documentation

For more information on the BeeAI Framework: https://framework.beeai.dev

## Roadmap

- [ ] **Improve multi-turn conversations** - Better context handling across multiple interactions
- [ ] **Add evaluation datasets** - Comprehensive testing with real-world issue examples  
- [ ] **MCP direct repository configuration** - Pre-configure the MCP tool with repository settings instead of relying on LLM to pass repository name
- [ ] **Improve agent configuration** - Configure GitHub repository from BeeAI Platform UI
- [ ] **Improve trajectory metadata** - Enhanced progress tracking and debugging capabilities
- [ ] **Add RAG instead of grounding** - Dynamic document retrieval for better context
- [ ] **Add streaming support** - Real-time response streaming for better UX
- [ ] **Build as Docker image** - Containerized deployment for easier hosting
- [ ] **Elicitation support** - Interactive tool use approval and clarification workflows

## Contributing

Feel free to submit improvements, additional templates, or new agent capabilities via pull requests.