/**
 * Type definitions for Upskill.
 */

export interface LLMConfig {
  model: string;
  temperature?: number;
  max_tokens?: number;
  [key: string]: unknown;
}

export interface MCPServerConfig {
  name: string;
  description?: string;
  transport: "stdio" | "streamable_http" | "http";
  // stdio transport
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  // http transport
  url?: string;
  headers?: Record<string, string>;
}

export interface SkillMetadata {
  name: string;
  description: string;
  tools: string[];
  content: string;
  references: Map<string, string>; // name -> file path
  scripts: Map<string, string>; // name -> file path
}

export interface AgentConfig {
  instructions: string;
  llm: LLMConfig;
  skills: SkillMetadata[];
  mcpServers: MCPServerConfig[];
  localToolPaths: string[];
  config: Record<string, unknown>;
}

export interface Message {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
}

export interface ToolCall {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string;
  };
}

export interface ToolSchema {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  source: string; // "mcp:<server_name>" or "local"
}

export interface SkillLoadResult {
  content: string;
  tools: string[];
  success: boolean;
}

export interface ReferenceLoadResult {
  content: string;
  success: boolean;
}

export interface ScriptLoadResult {
  content: string;
  language: string;
  success: boolean;
}
