---
name: weather-qa
description: Answer questions about current weather conditions and forecasts for any location. Use when the user asks about weather, temperature, rain, snow, or forecasts.
---

# Weather Q&A

Answer questions about current weather conditions and forecasts.

## Approach

1. Extract the location from the user's query (or ask if not provided)
2. Determine the time frame: current conditions, today, or multi-day forecast
3. Use the weather tool to fetch data
4. Present the information in a human-friendly format

## Response Format

For current weather:
- Temperature (with "feels like" if significantly different)
- Conditions (sunny, cloudy, rain, etc.)
- Wind and humidity if relevant

For forecasts:
- High/low temperatures
- Precipitation probability
- Notable weather events

## Units

- Default to Fahrenheit for US locations
- Default to Celsius for international locations
- Include both if the user's preference is unclear
