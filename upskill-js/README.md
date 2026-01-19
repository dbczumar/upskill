# Upskill (JavaScript/TypeScript)

**Turn skills, MCP tools, and AGENTS.md into a running agent (coding optional!)**

This is the JavaScript/TypeScript runtime for [Upskill](https://github.com/your-repo/upskill).

## Installation

```bash
npm install upskill
```

## Usage

### Basic Usage

```typescript
import { ChatAgent } from "upskill";

const agent = new ChatAgent("./my-agent");
await agent.initialize();

const response = await agent.run([
  { role: "user", content: "What's the weather in NYC?" }
]);
console.log(response);

await agent.close();
```

### Streaming

```typescript
import { ChatAgent } from "upskill";

const agent = new ChatAgent("./my-agent");
await agent.initialize();

for await (const token of agent.stream([
  { role: "user", content: "Tell me about the latest tech news" }
])) {
  process.stdout.write(token);
}

await agent.close();
```

### API

#### `ChatAgent`

- `new ChatAgent(path?: string)` - Create an agent from a directory (defaults to cwd)
- `initialize(): Promise<void>` - Initialize MCP connections and tools
- `run(messages): Promise<string>` - Run the agent
- `arun(messages): Promise<string>` - Alias for `run()`
- `stream(messages): AsyncGenerator<string>` - Run with streaming
- `astream(messages): AsyncGenerator<string>` - Alias for `stream()`
- `close(): Promise<void>` - Clean up resources
- `skills` - List of available skills
- `instructions` - The agent's AGENTS.md content

### Structured I/O with Zod

Use `Agent` for typed input/output with Zod schemas:

```typescript
import { Agent, z } from "upskill";

const QuerySchema = z.object({
  question: z.string().describe("The question to ask"),
  context: z.string().optional().describe("Additional context"),
});

const AnswerSchema = z.object({
  response: z.string().describe("The answer"),
  confidence: z.number().min(0).max(1).describe("Confidence score"),
});

const agent = new Agent({
  path: "./my-agent",
  inputSchema: QuerySchema,
  outputSchema: AnswerSchema,
});

await agent.initialize();
const result = await agent.run({ question: "What is machine learning?" });
console.log(result.response, result.confidence);
```

### Local Tools

Create tools in `tools/local/typescript/*.ts`:

```typescript
import { tool, z } from "upskill";

// With Zod schema validation
export const getWeather = tool({
  name: "get_weather",
  description: "Get the current weather for a location",
  parameters: z.object({
    location: z.string().describe("The city name"),
    units: z.enum(["celsius", "fahrenheit"]).optional().describe("Temperature units"),
  }),
}, async (args) => {
  return `Weather in ${args.location}: 72°F`;
});

// Simple tool without schema
import { simpleTool } from "upskill";

export const getCurrentTime = simpleTool(
  "Get the current time",
  () => new Date().toISOString()
);
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `UPSKILL_TOOL_TIMEOUT_MS` | `30000` | Tool call timeout |
| `UPSKILL_TOOL_MAX_RETRIES` | `3` | Max tool retries |
| `UPSKILL_TOOL_RETRY_BACKOFF_MS` | `1000` | Retry backoff |
| `UPSKILL_LLM_MAX_RETRIES` | `7` | LLM call retries |
| `UPSKILL_LLM_TIMEOUT_MS` | `120000` | LLM call timeout |
| `UPSKILL_MAX_AGENT_ITERATIONS` | `50` | Max agentic loop iterations |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `ANTHROPIC_API_KEY` | - | Anthropic API key |

## License

MIT
