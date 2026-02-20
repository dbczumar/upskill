"""
Loader — Reads agent repository by convention.

Loads:
- config.yaml → LLM settings (LiteLLM format)
- AGENTS.md → Agent instructions
- skills/*/SKILL.md → Skill metadata + content
- tools/mcp/*.yaml → MCP server configs
- tools/local/python/*.py → Local Python tools
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SkillMetadata:
    """Skill metadata from YAML frontmatter."""

    name: str
    description: str
    tools: list[str]  # Required tool names (e.g., ["news__fetch_feed_entries"])
    content: str  # Full markdown content (after frontmatter)
    path: Path
    references: dict[str, Path]  # Reference name -> file path (e.g., {"advanced-patterns": Path(...)})
    scripts: dict[str, Path]  # Script name -> file path (e.g., {"extract": Path(...)})

    @classmethod
    def from_skill_md(cls, path: Path) -> SkillMetadata:
        """Parse a SKILL.md file with YAML frontmatter."""
        text = path.read_text()

        # Parse YAML frontmatter (between --- markers)
        frontmatter_match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
        if not frontmatter_match:
            raise ValueError(f"SKILL.md must have YAML frontmatter: {path}")

        frontmatter_yaml = frontmatter_match.group(1)
        content = frontmatter_match.group(2).strip()

        frontmatter = yaml.safe_load(frontmatter_yaml)
        if not isinstance(frontmatter, dict):
            raise ValueError(f"Invalid frontmatter in {path}")

        name = frontmatter.get("name")
        description = frontmatter.get("description")
        tools = frontmatter.get("tools", [])

        if not name:
            raise ValueError(f"SKILL.md requires 'name' in frontmatter: {path}")
        if not description:
            raise ValueError(f"SKILL.md requires 'description' in frontmatter: {path}")
        if not isinstance(tools, list):
            raise ValueError(f"SKILL.md 'tools' must be a list: {path}")

        # Scan for references/ subdirectory
        references: dict[str, Path] = {}
        references_dir = path.parent / "references"
        if references_dir.is_dir():
            for ref_file in sorted(references_dir.glob("*.md")):
                ref_name = ref_file.stem  # e.g., "advanced-patterns"
                references[ref_name] = ref_file

        # Scan for scripts/ subdirectory (Python, Bash, JavaScript)
        scripts: dict[str, Path] = {}
        scripts_dir = path.parent / "scripts"
        if scripts_dir.is_dir():
            for pattern in ("*.py", "*.sh", "*.js"):
                for script_file in sorted(scripts_dir.glob(pattern)):
                    script_name = script_file.stem  # e.g., "extract"
                    scripts[script_name] = script_file

        return cls(
            name=name,
            description=description,
            tools=tools,
            content=content,
            path=path,
            references=references,
            scripts=scripts,
        )


@dataclass
class MCPServerConfig:
    """MCP server configuration."""

    name: str
    description: str
    transport: str  # "stdio" or "streamable_http" / "http"
    # For stdio transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # For HTTP transport
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> MCPServerConfig:
        """Parse an MCP server YAML config."""
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"Invalid MCP config in {path}")

        name = data.get("name")
        if not name:
            raise ValueError(f"MCP config requires 'name': {path}")

        return cls(
            name=name,
            description=data.get("description", ""),
            transport=data.get("transport", "stdio"),
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            url=data.get("url"),
            headers=data.get("headers", {}),
        )


@dataclass
class AgentConfig:
    """Complete agent configuration loaded from repository."""

    root: Path
    llm: dict[str, Any]
    config: dict[str, Any]
    interaction: dict[str, Any]
    instructions: str
    skills: list[SkillMetadata]
    mcp_servers: list[MCPServerConfig]
    local_tool_paths: list[Path]


def load_agent(path: str | Path | None = None) -> AgentConfig:
    """
    Load an agent repository from the given path.

    Args:
        path: Path to agent repository. Defaults to current directory.

    Returns:
        AgentConfig with all loaded components.
    """
    root = Path(path) if path else Path.cwd()
    if not root.is_dir():
        raise ValueError(f"Agent path must be a directory: {root}")

    # Load config.yaml
    llm_config: dict[str, Any] = {}
    app_config: dict[str, Any] = {}
    interaction_config: dict[str, Any] = {}
    config_path = root / "config.yaml"
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text()) or {}
        llm_config = data.get("llm", {})
        app_config = data.get("config", {})
        interaction_config = data.get("interaction", {})

    # Load AGENTS.md
    instructions = ""
    agents_md_path = root / "AGENTS.md"
    if agents_md_path.exists():
        instructions = agents_md_path.read_text()

    # Load skills from skills/*/SKILL.md
    skills: list[SkillMetadata] = []
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    skills.append(SkillMetadata.from_skill_md(skill_md))

    # Load MCP server configs from tools/mcp/*.yaml
    mcp_servers: list[MCPServerConfig] = []
    mcp_dir = root / "tools" / "mcp"
    if mcp_dir.is_dir():
        for yaml_file in sorted(mcp_dir.glob("*.yaml")):
            mcp_servers.append(MCPServerConfig.from_yaml(yaml_file))

    # Find local Python tool files
    local_tool_paths: list[Path] = []
    python_tools_dir = root / "tools" / "local" / "python"
    if python_tools_dir.is_dir():
        local_tool_paths = sorted(python_tools_dir.glob("*.py"))

    return AgentConfig(
        root=root,
        llm=llm_config,
        config=app_config,
        interaction=interaction_config,
        instructions=instructions,
        skills=skills,
        mcp_servers=mcp_servers,
        local_tool_paths=local_tool_paths,
    )
