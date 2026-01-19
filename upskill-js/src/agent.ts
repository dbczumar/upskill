/**
 * ChatAgent and Agent — Main user-facing interfaces for Upskill.
 */

import { z, ZodType, ZodObject, ZodRawShape } from "zod";
import type { AgentConfig, Message } from "./types.js";
import { loadAgent } from "./loader.js";
import { SkillManager } from "./skills.js";
import { ToolManager } from "./tools.js";
import { runAgenticLoop, runAgenticLoopStream } from "./loop.js";

/**
 * A chat agent loaded from an Upskill repository.
 *
 * @example
 * ```typescript
 * const agent = new ChatAgent("./my-agent");
 * await agent.initialize();
 *
 * const response = await agent.run([
 *   { role: "user", content: "Hello!" }
 * ]);
 * console.log(response);
 *
 * agent.close();
 * ```
 */
export class ChatAgent {
  private config: AgentConfig;
  private skillManager: SkillManager;
  private toolManager: ToolManager;
  private initialized = false;

  constructor(path?: string) {
    this.config = loadAgent(path);
    this.skillManager = new SkillManager(this.config.skills);
    this.toolManager = new ToolManager(
      this.config.mcpServers,
      this.config.localToolPaths,
      this.config.config
    );
  }

  /**
   * Initialize the agent (connect to MCP servers, load tools).
   * Must be called before run/stream methods.
   */
  async initialize(): Promise<void> {
    if (this.initialized) return;

    await this.toolManager.initialize();
    this.validateSkillTools();
    this.initialized = true;
  }

  /**
   * Warn if skills reference tools that don't exist.
   */
  private validateSkillTools(): void {
    const availableTools = new Set(this.toolManager.getToolNames());
    for (const skill of this.config.skills) {
      for (const toolName of skill.tools) {
        if (!availableTools.has(toolName)) {
          console.warn(
            `Warning: Skill '${skill.name}' requires tool '${toolName}' which is not available.`
          );
        }
      }
    }
  }

  /**
   * List of skill metadata (name and description).
   */
  get skills(): Array<{ name: string; description: string }> {
    return this.config.skills.map((s) => ({
      name: s.name,
      description: s.description,
    }));
  }

  /**
   * The agent's instructions from AGENTS.md.
   */
  get instructions(): string {
    return this.config.instructions;
  }

  private buildSystemPrompt(): string {
    const parts: string[] = [];

    if (this.config.instructions) {
      parts.push(this.config.instructions);
    }

    const skillSummary = this.skillManager.getSkillSummary();
    if (skillSummary) {
      parts.push(skillSummary);
    }

    return parts.join("\n\n");
  }

  /**
   * Run the agent with the given message history.
   */
  async run(messages: Array<{ role: string; content: string }>): Promise<string> {
    if (!this.initialized) {
      await this.initialize();
    }

    const systemPrompt = this.buildSystemPrompt();
    const formattedMessages: Message[] = messages.map((m) => ({
      role: m.role as Message["role"],
      content: m.content,
    }));

    return runAgenticLoop(
      formattedMessages,
      systemPrompt,
      this.config.llm,
      this.skillManager,
      this.toolManager
    );
  }

  /**
   * Alias for run() - async version (same behavior, for API consistency with Python).
   */
  async arun(messages: Array<{ role: string; content: string }>): Promise<string> {
    return this.run(messages);
  }

  /**
   * Run the agent with streaming, yielding tokens as they arrive.
   */
  async *stream(
    messages: Array<{ role: string; content: string }>
  ): AsyncGenerator<string, void, unknown> {
    if (!this.initialized) {
      await this.initialize();
    }

    const systemPrompt = this.buildSystemPrompt();
    const formattedMessages: Message[] = messages.map((m) => ({
      role: m.role as Message["role"],
      content: m.content,
    }));

    yield* runAgenticLoopStream(
      formattedMessages,
      systemPrompt,
      this.config.llm,
      this.skillManager,
      this.toolManager
    );
  }

  /**
   * Alias for stream() - async streaming (same behavior, for API consistency with Python).
   */
  async *astream(
    messages: Array<{ role: string; content: string }>
  ): AsyncGenerator<string, void, unknown> {
    yield* this.stream(messages);
  }

  /**
   * Close the agent and clean up resources.
   */
  async close(): Promise<void> {
    await this.toolManager.close();
    this.initialized = false;
  }
}

/**
 * Convert a Zod schema to a JSON Schema description for the system prompt.
 */
function zodSchemaToDescription(schema: ZodType): string {
  try {
    // Generate a simple JSON representation of the schema structure
    if (schema instanceof z.ZodObject) {
      const shape = schema.shape;
      const fields: string[] = [];

      for (const [key, value] of Object.entries(shape)) {
        const zodValue = value as ZodType;
        const typeStr = getZodTypeName(zodValue);
        const desc = zodValue.description ? ` - ${zodValue.description}` : "";
        const optional = zodValue.isOptional() ? "?" : "";
        fields.push(`  ${key}${optional}: ${typeStr}${desc}`);
      }

      return `{\n${fields.join("\n")}\n}`;
    }
    return "object";
  } catch {
    return "object";
  }
}

/**
 * Get a human-readable type name from a Zod type.
 */
function getZodTypeName(zodType: ZodType): string {
  if (zodType instanceof z.ZodString) return "string";
  if (zodType instanceof z.ZodNumber) return "number";
  if (zodType instanceof z.ZodBoolean) return "boolean";
  if (zodType instanceof z.ZodArray) return `${getZodTypeName(zodType.element)}[]`;
  if (zodType instanceof z.ZodEnum) return zodType.options.map((o: string) => `"${o}"`).join(" | ");
  if (zodType instanceof z.ZodOptional) return getZodTypeName(zodType.unwrap());
  if (zodType instanceof z.ZodNullable) return `${getZodTypeName(zodType.unwrap())} | null`;
  if (zodType instanceof z.ZodDefault) return getZodTypeName(zodType._def.innerType);
  if (zodType instanceof z.ZodObject) return "object";
  return "unknown";
}

/**
 * A typed agent with structured input/output schemas using Zod.
 *
 * @example
 * ```typescript
 * const QuerySchema = z.object({
 *   question: z.string().describe("The question to ask"),
 *   context: z.string().optional().describe("Additional context"),
 * });
 *
 * const AnswerSchema = z.object({
 *   response: z.string().describe("The answer"),
 *   confidence: z.number().min(0).max(1).describe("Confidence score"),
 * });
 *
 * const agent = new Agent({
 *   path: "./my-agent",
 *   inputSchema: QuerySchema,
 *   outputSchema: AnswerSchema,
 * });
 *
 * await agent.initialize();
 * const result = await agent.run({ question: "What is ML?" });
 * console.log(result.response, result.confidence);
 * ```
 */
export class Agent<
  TInput extends ZodRawShape,
  TOutput extends ZodRawShape
> {
  private config: AgentConfig;
  private skillManager: SkillManager;
  private toolManager: ToolManager;
  private initialized = false;

  private inputSchema: ZodObject<TInput>;
  private outputSchema: ZodObject<TOutput>;

  constructor(options: {
    path?: string;
    inputSchema: ZodObject<TInput>;
    outputSchema: ZodObject<TOutput>;
  }) {
    this.config = loadAgent(options.path);
    this.skillManager = new SkillManager(this.config.skills);
    this.toolManager = new ToolManager(
      this.config.mcpServers,
      this.config.localToolPaths,
      this.config.config
    );
    this.inputSchema = options.inputSchema;
    this.outputSchema = options.outputSchema;
  }

  /**
   * Initialize the agent (connect to MCP servers, load tools).
   */
  async initialize(): Promise<void> {
    if (this.initialized) return;

    await this.toolManager.initialize();
    this.validateSkillTools();
    this.initialized = true;
  }

  private validateSkillTools(): void {
    const availableTools = new Set(this.toolManager.getToolNames());
    for (const skill of this.config.skills) {
      for (const toolName of skill.tools) {
        if (!availableTools.has(toolName)) {
          console.warn(
            `Warning: Skill '${skill.name}' requires tool '${toolName}' which is not available.`
          );
        }
      }
    }
  }

  get skills(): Array<{ name: string; description: string }> {
    return this.config.skills.map((s) => ({
      name: s.name,
      description: s.description,
    }));
  }

  get instructions(): string {
    return this.config.instructions;
  }

  private buildSystemPrompt(): string {
    const parts: string[] = [];

    if (this.config.instructions) {
      parts.push(this.config.instructions);
    }

    const skillSummary = this.skillManager.getSkillSummary();
    if (skillSummary) {
      parts.push(skillSummary);
    }

    // Add output format instructions
    const schemaDesc = zodSchemaToDescription(this.outputSchema);
    parts.push(
      `## Output Format\n\n` +
      `You must respond with valid JSON matching this schema:\n` +
      `\`\`\`\n${schemaDesc}\n\`\`\``
    );

    return parts.join("\n\n");
  }

  /**
   * Run the agent with typed input and get typed output.
   */
  async run(input: z.infer<ZodObject<TInput>>): Promise<z.infer<ZodObject<TOutput>>> {
    if (!this.initialized) {
      await this.initialize();
    }

    // Validate input
    const validatedInput = this.inputSchema.parse(input);

    const systemPrompt = this.buildSystemPrompt();
    const inputStr = JSON.stringify(validatedInput);
    const messages: Message[] = [{ role: "user", content: inputStr }];

    const result = await runAgenticLoop(
      messages,
      systemPrompt,
      this.config.llm,
      this.skillManager,
      this.toolManager
    );

    // Parse and validate output
    try {
      const parsed = JSON.parse(result);
      return this.outputSchema.parse(parsed);
    } catch (e) {
      throw new Error(`Failed to parse agent output as valid schema: ${e}\nRaw output: ${result}`);
    }
  }

  /**
   * Alias for run() - async version.
   */
  async arun(input: z.infer<ZodObject<TInput>>): Promise<z.infer<ZodObject<TOutput>>> {
    return this.run(input);
  }

  /**
   * Close the agent and clean up resources.
   */
  async close(): Promise<void> {
    await this.toolManager.close();
    this.initialized = false;
  }
}

// Re-export for convenience
export { SkillManager } from "./skills.js";
export { ToolManager, tool, simpleTool } from "./tools.js";
export type { AgentConfig, Message, ToolSchema } from "./types.js";
export { z } from "zod";
