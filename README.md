# Upskill

**Turn skills and tools into a running agent.**

Upskill is a minimal, runtime-driven system for composing [Agent Skills](https://agentskills.io), [MCP](https://modelcontextprotocol.io) tools, code-based tools, and agent instructions into a working agent — without writing any runtime code.

## Why Upskill?

[Agent Skills](https://agentskills.io) and [AGENTS.md](https://agents.md/) are powerful innovations that emerged from coding assistants like Claude Code and OpenAI Codex. Combined with [MCP](https://modelcontextprotocol.io) for tool integration, they form a complete foundation for building agents. But there's nothing code-specific about them — **they're general-purpose building blocks for any high-quality agent**.

Upskill brings these standards to **all agent use cases**: chatbots, document analyzers, research assistants, workflow automation, and beyond.

Today, building an agent requires wiring together skills, tools, LLM configuration, and execution logic in code. Upskill separates **what your agent knows** from **how it runs**:

- **Agent repositories** contain declarative content (markdown, YAML) — no code required
- **Upskill runtimes** handle execution, planning, and tool invocation
- **Code is supported** when you need it — add custom tools in Python or other languages

This means:
- Skills are portable across Claude Code, OpenAI Codex, GitHub Copilot, and Upskill
- MCP tools work without custom adapters
- No vendor lock-in — swap LLM providers via config
- Agent repos are human-readable and version-controllable
- Start simple, add code only when your use case demands it

## Core Philosophy

- **Multi-runtime** — the format works across Python, TypeScript, and any language with an Upskill runtime
- **Ecosystem-native** — built on [Agent Skills](https://agentskills.io), [AGENTS.md](https://agents.md/), and [MCP](https://modelcontextprotocol.io), not a new standard
- **Human-readable** — markdown and YAML that humans can write and review
- **Code optional** — add programmatic tools when you need them, but they're not required

## How It Compares

|  | Human-readable | Industry standards | Any use case | No code required |
|--|----------------|-------------------|--------------|------------------|
| **Coding assistants** (Claude Code, Codex) | ✅ | ✅ Skills, AGENTS.md, MCP | ❌ Coding-only | ✅ |
| **No-code agent builders** | ❌ Black box | ❌ Proprietary | ✅ | ✅ |
| **Agent frameworks** (LangChain, CrewAI) | ❌ Code is the format | ❌ Framework-specific | ✅ | ❌ |
| **Declarative specs** (Oracle Agent Spec) | ⚠️ Schema-heavy | ❌ New spec | ✅ | ✅ |
| **Upskill** | ✅ Markdown + YAML | ✅ Skills, AGENTS.md, MCP | ✅ | ✅ Optional, not required |

Upskill brings the human-readable, standards-based approach pioneered by coding assistants to **any kind of agent**.

## Repository Structure

An Upskill agent repository follows this convention:

```
my-agent/
├── config.yaml          # LLM and runtime configuration
├── AGENTS.md            # Agent identity and behavior (optional)
├── skills/              # Procedural knowledge (Agent Skills spec)
│   ├── skill-one/
│   │   └── SKILL.md
│   └── skill-two/
│       └── SKILL.md
├── tools/               # Tool definitions (optional)
│   ├── mcp/             # MCP server configs
│   │   └── *.yaml
│   └── local/           # Local tool implementations
│       └── python/
│           └── *.py
└── README.md
```

---

## config.yaml

Runtime configuration using [LiteLLM](https://docs.litellm.ai/) model format:

```yaml
llm:
  model: openai/gpt-4o          # or anthropic/claude-3-5-sonnet, etc.
  temperature: 0.2
  max_tokens: 4096

config:
  # Add agent-specific configuration here
  api_key_for_service:          # Required values have no default
  # optional_setting: value     # Commented = disabled
```

Values can be resolved from environment variables, CLI flags, or interactive prompts.

---

## AGENTS.md

Optional file defining the agent's identity and behavioral guidelines, following the [AGENTS.md standard](https://agents.md/):

```markdown
# My Agent

You are a helpful assistant that specializes in...

## Identity

- **Name**: AgentName
- **Personality**: Friendly and concise

## What You Can Do

- Task one
- Task two

## How to Respond

- Always cite sources
- Be concise
```

Think of it as a repo-scoped system prompt.

---

## Skills

Skills are procedural knowledge following the [Agent Skills specification](https://agentskills.io/specification).

Each skill is a directory containing a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: my-skill
description: Does X when the user asks about Y. Use for Z scenarios.
---

# My Skill

Step-by-step instructions for the agent...
```

### Required Frontmatter

| Field | Constraints |
|-------|-------------|
| `name` | Lowercase, numbers, hyphens. Must match directory name. Max 64 chars. |
| `description` | What it does and when to use it. Max 1024 chars. |

### Optional Frontmatter

| Field | Purpose |
|-------|---------|
| `license` | License name |
| `metadata` | Author, version, etc. |
| `allowed-tools` | Restrict which tools this skill can use |

Skills are **portable** — they work in Claude Code, OpenAI Codex, GitHub Copilot, and any Agent Skills-compatible system.

---

## Tools

Upskill discovers tools by convention from the `tools/` directory.

### MCP Tools

Place MCP server configurations in `tools/mcp/*.yaml`:

**Local process (stdio):**
```yaml
name: filesystem
description: File system access
transport: stdio
command: npx
args:
  - -y
  - "@modelcontextprotocol/server-filesystem"
  - "."
```

**Remote server (HTTP):**
```yaml
name: weather
description: Weather data via Open-Meteo
transport: streamable_http
url: https://mcp.example.com/weather/mcp
headers:
  Authorization: ${API_KEY}
```

### Local Tools

Place code-based tools in `tools/local/<language>/`:

```
tools/local/
├── python/*.py
├── typescript/*.ts
└── ...
```

**Example (Python):**

```python
from upskill import tool

@tool
def my_tool(param: str) -> str:
    """Short description of what this tool does.

    Args:
        param: Description of the parameter.
    """
    return result
```

Tool implementation varies by runtime. See your runtime's documentation for supported languages and decorators.

---

## Running an Agent (Python)

Install the Python runtime:

```bash
pip install upskill
```

### Basic Usage

```python
from upskill import ChatAgent

# Load agent from a directory
agent = ChatAgent("./my-agent")

# Run a conversation
response = agent.run([
    {"role": "user", "content": "What's the weather in NYC?"}
])
print(response)
```

### Async

```python
import asyncio
from upskill import ChatAgent

agent = ChatAgent("./my-agent")

async def main():
    response = await agent.arun([
        {"role": "user", "content": "What's 25 * 13?"}
    ])
    print(response)

asyncio.run(main())
```

### Streaming

```python
from upskill import ChatAgent

agent = ChatAgent("./my-agent")

# Sync streaming
for token in agent.stream([
    {"role": "user", "content": "Tell me about the latest tech news"}
]):
    print(token, end="", flush=True)
```

### Async Streaming

```python
import asyncio
from upskill import ChatAgent

agent = ChatAgent("./my-agent")

async def main():
    async for token in agent.astream([
        {"role": "user", "content": "What's 100 divided by 8?"}
    ]):
        print(token, end="", flush=True)

asyncio.run(main())
```

### Structured Output

Use `Agent` for typed input/output with Pydantic models:

```python
from pydantic import BaseModel
from upskill import Agent

class Question(BaseModel):
    query: str
    context: str | None = None

class Answer(BaseModel):
    response: str
    confidence: float

agent = Agent[Question, Answer](
    input_schema=Question,
    output_schema=Answer,
    path="./my-agent",
)

result = agent.run(Question(query="What is machine learning?"))
print(result.response, result.confidence)
```

---

## Example

See [`examples/sidekick_chatbot`](examples/sidekick_chatbot) for a complete example agent with:
- Three skills (news, weather, math)
- MCP tools (remote and local)
- Local Python tools
- Agent identity via AGENTS.md

## Resources

- [Design Specification](design)
- [AGENTS.md Standard](https://agents.md/)
- [Agent Skills Specification](https://agentskills.io/specification)
- [Model Context Protocol](https://modelcontextprotocol.io)
