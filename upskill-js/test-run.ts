/**
 * Quick test to verify the runtime works.
 */

import { ChatAgent } from "./dist/index.js";
import * as path from "path";

async function main() {
  const agentPath = path.join(import.meta.dirname, "..", "examples", "sidekick_chatbot");

  console.log("Loading agent from:", agentPath);

  const agent = new ChatAgent(agentPath);

  console.log("Skills:", agent.skills);
  console.log("Instructions preview:", agent.instructions.slice(0, 200) + "...");

  console.log("\nInitializing...");
  await agent.initialize();

  console.log("\nRunning query...");
  const response = await agent.run([
    { role: "user", content: "What's 15% of 200?" }
  ]);

  console.log("\nResponse:", response);

  await agent.close();
}

main().catch(console.error);
