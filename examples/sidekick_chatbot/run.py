"""
Example usage of the Upskill Python runtime.

This script demonstrates how to load and run the Sidekick chatbot agent.
"""

from upskill import ChatAgent

# Load agent from current directory
agent = ChatAgent()

# Show loaded components
print("=== Instructions ===")
print(agent.instructions[:200] + "...")

print("\n=== Skills ===")
print(agent.skills)

print("\n=== News Example ===")
response = agent.run(
    messages=[{"role": "user", "content": "What's happening in tech news today?"}]
)
print(response.content)

print("\n=== Weather Example ===")
response = agent.run(messages=[{"role": "user", "content": "What's the weather in NYC?"}])
print(response.content)

print("\n=== Calculation Example ===")
response = agent.run(
    messages=[{"role": "user", "content": "Calculate 15% of 847 to 3 decimal places"}]
)
print(response.content)

print("\n=== Compound Interest Example ===")
response = agent.run(
    messages=[{"role": "user", "content": "What's the compound interest on $5000 at 6% for 10 years?"}]
)
print(response.content)
