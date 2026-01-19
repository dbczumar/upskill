/**
 * Upskill - Turn skills and tools into a running agent.
 */

export { ChatAgent, Agent, SkillManager, ToolManager, tool, simpleTool, z } from "./agent.js";
export { loadAgent } from "./loader.js";
export type {
  AgentConfig,
  LLMConfig,
  MCPServerConfig,
  Message,
  SkillMetadata,
  ToolInfo,
  ToolSchema,
} from "./types.js";
