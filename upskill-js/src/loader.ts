/**
 * Agent Loader — Load agent configuration from a repository.
 */

import * as fs from "fs";
import * as path from "path";
import * as yaml from "js-yaml";
import matter from "gray-matter";
import type {
  AgentConfig,
  LLMConfig,
  MCPServerConfig,
  SkillMetadata,
} from "./types.js";

const DEFAULT_LLM_CONFIG: LLMConfig = {
  model: "openai/gpt-4o",
  temperature: 0.2,
  max_tokens: 4096,
};

/**
 * Load an agent from a directory.
 */
export function loadAgent(agentPath?: string): AgentConfig {
  const basePath = agentPath || process.cwd();

  // Load config.yaml
  const configPath = path.join(basePath, "config.yaml");
  let configData: Record<string, unknown> = {};
  if (fs.existsSync(configPath)) {
    const content = fs.readFileSync(configPath, "utf-8");
    configData = yaml.load(content) as Record<string, unknown>;
  }

  // Extract LLM config
  const llmConfig: LLMConfig = {
    ...DEFAULT_LLM_CONFIG,
    ...((configData.llm as LLMConfig) || {}),
  };

  // Extract custom config
  const config = (configData.config as Record<string, unknown>) || {};

  // Load AGENTS.md
  const agentsPath = path.join(basePath, "AGENTS.md");
  let instructions = "";
  if (fs.existsSync(agentsPath)) {
    instructions = fs.readFileSync(agentsPath, "utf-8");
  }

  // Load skills
  const skills = loadSkills(basePath);

  // Load MCP server configs
  const mcpServers = loadMCPServers(basePath);

  // Discover local tool paths
  const localToolPaths = discoverLocalTools(basePath);

  return {
    instructions,
    llm: llmConfig,
    skills,
    mcpServers,
    localToolPaths,
    config,
  };
}

/**
 * Load all skills from the skills/ directory.
 */
function loadSkills(basePath: string): SkillMetadata[] {
  const skillsDir = path.join(basePath, "skills");
  if (!fs.existsSync(skillsDir)) {
    return [];
  }

  const skills: SkillMetadata[] = [];
  const entries = fs.readdirSync(skillsDir, { withFileTypes: true });

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;

    const skillPath = path.join(skillsDir, entry.name, "SKILL.md");
    if (!fs.existsSync(skillPath)) continue;

    const content = fs.readFileSync(skillPath, "utf-8");
    const { data: frontmatter, content: body } = matter(content);

    const name = (frontmatter.name as string) || entry.name;
    const description = (frontmatter.description as string) || "";
    const tools = (frontmatter.tools as string[]) || [];

    // Load references
    const references = new Map<string, string>();
    const refsDir = path.join(skillsDir, entry.name, "references");
    if (fs.existsSync(refsDir)) {
      for (const refFile of fs.readdirSync(refsDir)) {
        if (refFile.endsWith(".md")) {
          const refName = refFile.replace(/\.md$/, "");
          references.set(refName, path.join(refsDir, refFile));
        }
      }
    }

    // Load scripts
    const scripts = new Map<string, string>();
    const scriptsDir = path.join(skillsDir, entry.name, "scripts");
    if (fs.existsSync(scriptsDir)) {
      for (const scriptFile of fs.readdirSync(scriptsDir)) {
        const ext = path.extname(scriptFile);
        if ([".py", ".js", ".ts", ".sh"].includes(ext)) {
          const scriptName = scriptFile.replace(ext, "");
          scripts.set(scriptName, path.join(scriptsDir, scriptFile));
        }
      }
    }

    skills.push({
      name,
      description,
      tools,
      content: body.trim(),
      references,
      scripts,
    });
  }

  return skills;
}

/**
 * Load MCP server configurations from tools/mcp/*.yaml
 */
function loadMCPServers(basePath: string): MCPServerConfig[] {
  const mcpDir = path.join(basePath, "tools", "mcp");
  if (!fs.existsSync(mcpDir)) {
    return [];
  }

  const servers: MCPServerConfig[] = [];
  const files = fs.readdirSync(mcpDir).filter((f) => f.endsWith(".yaml"));

  for (const file of files) {
    const content = fs.readFileSync(path.join(mcpDir, file), "utf-8");
    const config = yaml.load(content) as MCPServerConfig;
    servers.push(config);
  }

  return servers;
}

/**
 * Discover local tool files from tools/local/<language>/*.
 */
function discoverLocalTools(basePath: string): string[] {
  const localDir = path.join(basePath, "tools", "local");
  if (!fs.existsSync(localDir)) {
    return [];
  }

  const toolPaths: string[] = [];
  const languages = fs.readdirSync(localDir, { withFileTypes: true });

  for (const lang of languages) {
    if (!lang.isDirectory()) continue;

    // For now, only support TypeScript/JavaScript tools
    if (!["typescript", "javascript", "ts", "js"].includes(lang.name)) continue;

    const langDir = path.join(localDir, lang.name);

    // For TypeScript, prefer compiled files in dist/
    if (lang.name === "typescript" || lang.name === "ts") {
      const distDir = path.join(langDir, "dist");
      if (fs.existsSync(distDir)) {
        const files = fs.readdirSync(distDir);
        for (const file of files) {
          if (file.endsWith(".js")) {
            toolPaths.push(path.join(distDir, file));
          }
        }
        continue;
      }
    }

    // Otherwise look for JS files directly
    const files = fs.readdirSync(langDir);
    for (const file of files) {
      if (file.endsWith(".js")) {
        toolPaths.push(path.join(langDir, file));
      }
    }
  }

  return toolPaths;
}
