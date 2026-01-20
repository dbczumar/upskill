"""
Interactive chat with the Sidekick agent.

Usage:
    OPENAI_API_KEY="sk-..." python chat.py

Debug mode:
    OPENAI_API_KEY="sk-..." UPSKILL_DEBUG=true python chat.py
"""

from upskill import ChatAgent

def main():
    # Load and initialize agent
    print("Loading Sidekick agent...")
    agent = ChatAgent()

    print("\nSidekick ready! Type 'quit' to exit.\n")
    print("Try asking about:")
    print("  - Weather: 'What's the weather in San Francisco?'")
    print("  - News: 'What's happening in tech news?'")
    print("  - Math: 'What's 15% of 847?'\n")

    messages = []

    while True:
        try:
            user_input = input("You: ")
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.lower() == "quit":
            break

        messages.append({"role": "user", "content": user_input})

        print("\nSidekick: ", end="", flush=True)

        # Stream the response
        full_response = ""
        for event in agent.stream(messages):
            if event.type == "content":
                print(event.content, end="", flush=True)
                full_response += event.content

        print("\n")
        messages.append({"role": "assistant", "content": full_response})

    agent.close()
    print("Goodbye!")


if __name__ == "__main__":
    main()
