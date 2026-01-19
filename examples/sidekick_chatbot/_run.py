"""
Example usage of the Upskill Python runtime.

This script demonstrates how to load and run the Sidekick chatbot agent.
"""

import logging
handler = logging.StreamHandler()
logging.getLogger("upskill").setLevel(logging.DEBUG)
handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
logger = logging.getLogger("upskill")
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

from upskill import ChatAgent

import time

# Load agent from current directory

t1 = time.time()
agent = ChatAgent()

# Show loaded components
# print("Skills:", agent.skills)
# print("Tools:", agent.tools)
# print("Instructions:", agent.instructions)
# print("Instructions:", agent.instructions[:200] + "...")

# Example: Ask about news
# response = agent.run(
#     messages=[{"role": "user", "content": "What's happening in tech news today?"}]
# )
# print("Response:", response)

# Other examples to try:
# response = agent.run(messages=[{"role": "user", "content": "What's the weather in NYC?"}])
# print("Response:", response)

t2 = time.time()
print(t2 - t1)


# Example: Non-streaming run
# response = agent.run(messages=[{"role": "user", "content": "What would 5672.3 dollars compounded monthly at 7% look like after 8.4 years?"}])
# t3 = time.time()
# print(t3 - t2)
# print("Response:", response)

# Example: Streaming response (sync)
print("\n--- stream() Example ---\n")
for event in agent.stream(
    messages=[{"role": "user", "content": "What's the weather in NYC?"}]
):
    if event.type == "content":
        print(event.content, end="", flush=True)
print("\n")

t3 = time.time()
print(f"stream() took {t3 - t2:.2f}s")


# Example: Async run
import asyncio

async def run_arun_example():
    print("\n--- arun() Example ---\n")
    t_start = time.time()
    response = await agent.arun(
        messages=[{"role": "user", "content": "What's 25 * 13?"}]
    )
    print("Response:", response.content)
    print(f"arun() took {time.time() - t_start:.2f}s")

asyncio.run(run_arun_example())


# Example: Async streaming
async def run_astream_example():
    print("\n--- astream() Example ---\n")
    t_start = time.time()
    async for event in agent.astream(
        messages=[{"role": "user", "content": "What's 100 divided by 8?"}]
    ):
        if event.type == "content":
            print(event.content, end="", flush=True)
    print(f"\n\nastream() took {time.time() - t_start:.2f}s")

asyncio.run(run_astream_example())
