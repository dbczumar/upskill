/**
 * Interactive chat with the Sidekick agent.
 *
 * Usage:
 *   OPENAI_API_KEY="sk-..." npx tsx chat.ts
 *
 * Debug mode:
 *   OPENAI_API_KEY="sk-..." UPSKILL_DEBUG=true npx tsx chat.ts
 */

import * as readline from "node:readline/promises";
import { ChatAgent, type Message } from "../../upskill-js/dist/index.js";

async function main() {
  const terminal = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  // Load and initialize agent
  console.log("Loading Sidekick agent...");
  const agent = new ChatAgent(import.meta.dirname);
  await agent.initialize();

  console.log("\nSidekick ready! Type 'quit' to exit.\n");
  console.log("Try asking about:");
  console.log("  - Weather: 'What's the weather in San Francisco?'");
  console.log("  - News: 'What's happening in tech news?'");
  console.log("  - Math: 'What's 15% of 847?'\n");

  const messages: Message[] = [];

  while (true) {
    const userInput = await terminal.question("You: ");

    if (userInput.toLowerCase() === "quit") {
      break;
    }

    messages.push({ role: "user", content: userInput });

    process.stdout.write("\nSidekick: ");

    // Stream the response
    let fullResponse = "";
    for await (const chunk of agent.stream(messages)) {
      process.stdout.write(chunk);
      fullResponse += chunk;
    }

    console.log("\n");
    messages.push({ role: "assistant", content: fullResponse });
  }

  await agent.close();
  terminal.close();
  console.log("Goodbye!");
}

main().catch(console.error);
