---
name: weather-qa
description: Answer questions about current weather conditions and forecasts for any location. Use when the user asks about weather, temperature, rain, snow, or forecasts.
tools:
  - get_forecast
  - get_current_conditions
  - get_alerts
  - search_location
  - current_time
---

# Weather Q&A

Answer questions about current weather conditions and forecasts.

## Approach

1. Extract the location from the user's query (or ask if not provided)
2. Determine the time frame: current conditions, today, or multi-day forecast
3. Get coordinates for the location:
   - Try `search_location` first with the city name
   - If search fails, use known coordinates for major cities (see below)
   - If unknown, ask the user for coordinates or a nearby major city
4. Use `get_forecast` or `get_current_conditions` with latitude/longitude
5. Present the information in a human-friendly format

## Common City Coordinates

Use these if `search_location` fails:

| City | Latitude | Longitude |
|------|----------|-----------|
| San Francisco | 37.7749 | -122.4194 |
| New York | 40.7128 | -74.0060 |
| Los Angeles | 34.0522 | -118.2437 |
| Chicago | 41.8781 | -87.6298 |
| Seattle | 47.6062 | -122.3321 |
| Miami | 25.7617 | -80.1918 |
| Boston | 42.3601 | -71.0589 |
| Denver | 39.7392 | -104.9903 |
| London | 51.5074 | -0.1278 |
| Paris | 48.8566 | 2.3522 |
| Tokyo | 35.6762 | 139.6503 |
| Sydney | -33.8688 | 151.2093 |

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

## Local Time

Use `current_time` to show the local time at the queried location. This helps users understand the context (e.g., "It's currently 3am in Tokyo, and the temperature is...").
