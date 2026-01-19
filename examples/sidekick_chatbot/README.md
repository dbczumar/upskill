# Sidekick Chatbot

A demonstration chatbot that answers questions about sports, weather, and performs calculations.

## Features

- **Sports Q&A**: Scores, standings, schedules, and player statistics
- **Weather Q&A**: Current conditions and forecasts for any location
- **Math & Computation**: Run Python code for calculations and data analysis

## Setup

1. Set required environment variables:
   ```bash
   # Get your API key at https://www.balldontlie.io/
   export BALLDONTLIE_API_KEY="your-api-key"
   ```

   Note: Weather uses [Open-Meteo](https://open-meteo.com/) via [open-mcp.org](https://open-mcp.org/) — no API key required.

2. Install `uv` (for the code interpreter):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. Run with an Upskill runtime:
   ```bash
   upskill run examples/sidekick_chatbot
   ```

## Directory Structure

```
sidekick_chatbot/
├── config.yaml          # Runtime configuration
├── AGENTS.md            # Agent identity and behavior
├── skills/
│   ├── sports-qa/       # Sports question answering
│   ├── weather-qa/      # Weather question answering
│   └── math-calculator/ # Math via code interpreter
└── tools/mcp/
    ├── weather.yaml         # Open-Meteo (streamable HTTP)
    ├── sports.yaml          # BALLDONTLIE (HTTP)
    └── code_interpreter.yaml # Pydantic mcp-run-python (stdio)
```

## MCP Tools

| Tool | Source | Transport |
|------|--------|-----------|
| weather | [open-mcp.org](https://open-mcp.org/) | streamable HTTP |
| sports | [BALLDONTLIE](https://balldontlie.io/) | HTTP |
| code_interpreter | [mcp-run-python](https://github.com/pydantic/mcp-run-python) | stdio (local) |
