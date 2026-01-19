/**
 * Example usage of the Upskill TypeScript runtime.
 *
 * This script demonstrates how to load and run the Sidekick chatbot agent.
 *
 * Usage:
 *   OPENAI_API_KEY="sk-..." npx tsx run.ts
 */

import { ChatAgent } from "../../upskill-js/dist/index.js";

async function main() {
  // Load agent from current directory
  const agent = new ChatAgent(import.meta.dirname);

  // Show loaded components
  console.log("=== Instructions ===");
  console.log(agent.instructions.slice(0, 200) + "...");

  console.log("\n=== Skills ===");
  console.log(agent.skills);

  // Initialize MCP servers
  console.log("\n=== Initializing ===");
  await agent.initialize();

  console.log("\n=== News Example ===");
  const newsResponse = await agent.run([
    { role: "user", content: "What's happening in tech news today?" },
  ]);
  console.log(newsResponse);

  console.log("\n=== Weather Example ===");
  const weatherResponse = await agent.run([
    { role: "user", content: "What's the weather in NYC?" },
  ]);
  console.log(weatherResponse);

  console.log("\n=== Calculation Example ===");
  const calcResponse = await agent.run([
    { role: "user", content: "Calculate 15% of 847 to 3 decimal places" },
  ]);
  console.log(calcResponse);

  console.log("\n=== Compound Interest Example ===");
  const interestResponse = await agent.run([
    { role: "user", content: "What's the compound interest on $5000 at 6% for 10 years?" },
  ]);
  console.log(interestResponse);

  // Clean up
  await agent.close();
}

main().catch(console.error);
