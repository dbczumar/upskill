# Sidekick Chatbot

A demonstration chatbot that answers questions about news, weather, and performs calculations.

## Features

- **News & Current Events**: Headlines from BBC, NPR, TechCrunch, Hacker News, and more via RSS
- **Weather Q&A**: Current conditions and forecasts for any location
- **Math & Calculations**: Arithmetic, percentages, statistics, unit conversions

## Setup

1. Install the upskill-py runtime:
   ```bash
   cd upskill-py && pip install -e .
   ```

2. Set environment variables:
   ```bash
   export OPENAI_API_KEY="your-openai-key"
   ```

3. Run from the sidekick_chatbot directory:
   ```python
   from upskill import ChatAgent

   agent = ChatAgent()
   response = agent.run(messages=[{"role": "user", "content": "What's in the news today?"}])
   print(response)
   ```

## Directory Structure

```
sidekick_chatbot/
├── config.yaml          # LLM and runtime configuration
├── AGENTS.md            # Agent identity and behavior
├── skills/
│   ├── news-qa/         # News and current events
│   ├── weather-qa/      # Weather question answering
│   └── math-calculator/ # Math calculations
└── tools/mcp/
    ├── news.yaml             # RSS feed reader (no API key needed)
    ├── weather.yaml          # Weather via NOAA/Open-Meteo (no API key needed)
    └── code_interpreter.yaml # Python code execution
```

## MCP Tools

| Tool | Source |
|------|--------|
| news | [rss-reader-mcp](https://www.npmjs.com/package/rss-reader-mcp) |
| weather | [@dangahagan/weather-mcp](https://www.npmjs.com/package/@dangahagan/weather-mcp) |
| code_interpreter | [mcp-python-interpreter](https://pypi.org/project/mcp-python-interpreter/) |
