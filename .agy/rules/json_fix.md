---
description: Fix for local LLMs emitting invalid JSON and hallucinating tool names
---

# JSON Formatting and Tool Calls

When you are calling a tool that executes commands (such as running a bash command), you MUST follow these strict rules to ensure the JSON payload parses correctly:

1. Use the exact tool name provided to you (e.g., `run_command`), DO NOT hallucinate plural versions like `run_commands`.
2. You MUST escape all newlines in the command strings with `\n`. DO NOT include raw newline characters in the JSON values.
3. You MUST escape all double quotes within strings with `\"`. 
4. Ensure the outer structure is perfectly valid, strictly-formatted JSON.
