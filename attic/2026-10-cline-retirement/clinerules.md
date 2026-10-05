# JSON Formatting and Tool Calls

When you are calling a tool that executes commands (such as executing a bash command or writing a file), you MUST follow these strict rules to ensure the JSON payload parses correctly through local models:

1. You MUST escape all newlines in the command strings with `\n`. DO NOT include raw newline characters in the JSON values.
2. You MUST escape all double quotes within strings with `\"`. 
3. Ensure the outer structure is perfectly valid, strictly-formatted JSON.
4. Do not hallucinate tools. Use exact tool names.
