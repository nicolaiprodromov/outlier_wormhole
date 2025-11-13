# Copilot Chat Agent — Research Summary

This document summarizes how the Copilot chat agent (VS Code) works at a code-level: agent lifecycle & loop, how system/user messages are assembled into prompts, how tools are registered & exposed to models, how tool calls are represented in model outputs, how the extension invokes tools, and example payload shapes for client-to-model and model-to-client (tool call delta) communications.

This doc is drawn from reading the Copilot Chat extension code (prompt renderers, endpoint adapters, tool-calling loop, ChatML fetchers, and tests) and from inspecting test snapshots and stream-handling code. Paths below reference files in the typical VS Code Copilot Chat repo; paths may vary slightly depending on repo release.

---

## TL;DR

- The agent builds a prompt from: system messages (identity, safety & developer instructions) + global agent context (workspace, files, settings) + user instructions + past assistant messages and tool results.
- Tools are represented as function-like schemas included in the request body (name, description, inputSchema) and are sent to LLM endpoints that support tool/function calling.
- Models return streaming deltas which include text parts and tool call parts (LanguageModelToolCallPart or, in CAPI, function_call objects). The extension's fetcher captures as delta.copilotToolCalls.
- A tool-calling loop inspects deltas for tool-calls, invokes the tools (validate/resolve input), captures the result (and errors), and reinserts a 'tool result' message back into the conversation; this can lead to further LLM iterations.

---

## 1. Agent lifecycle & loop (high-level)

1. Build the prompt (agentPrompt.tsx):
   - Add system instructions with general assistant role and experiment flags.
   - Add global context (workspace metadata, file changes, repository metadata).
   - Add user prompt (query).
   - Append last assistant messages and tool results in chronological order.

2. Choose tools to expose (agentIntent.ts and getAgentTools):
   - Tools are filtered by the selected model’s capabilities (some endpoints only support functions).
   - Tools may be enabled/disabled by experiments or user preferences.

3. Make a chat request to the model endpoint (chatMLFetcher.ts, extChatEndpoint.ts, networking.ts):
   - Build the request body with messages and the tools/function definitions.
   - Send it to the selected endpoint (CAPI, extension-contributed LanguageModel, BYOK, etc.) via a streaming path.

4. Stream deltas and capture copilotToolCalls (FetchStreamRecorder/StreamRecorder):
   - Text deltas update the visible assistant content.
   - Tool-call deltas are captured as action objects with {name, arguments, id}.

5. When a tool call is seen, invoke the tool via the tool registry (toolsService):
   - Validate & convert the tool arguments.
   - Run the tool implementation (file read, shell command, applyPatch, readFile, etc.).
   - Return a tool result (success/ failure) with result payload and any debug info.

6. Append the tool result into the conversation history as a special ToolResult message, and repeat the request to the model (or resume streaming) to continue the dialog.

7. Maintain token budgets and summarization: If prompts are too large, summarization is triggered and the prompt is rebuilt using the summary.

---

## 2. Where system vs user messages are inserted

- System messages:
  - Created by the agentPrompt and are placed at the top of the final `messages` array that gets sent to the model. They include assistant identity, safety guard rails, and mode-specific instructions (e.g., code assistant vs code + shell).

- User messages:
  - Inserted after the system messages and global context. The user message typically contains the actual query or task.

- Tool results / assistant messages:
  - Past assistant responses, tool results, and previously executed toolCalls are appended in a chronological order as conversation history, just like a chat. Tool results are often included as a JSON-coded block or strict structured message.

- These elements are all rendered into the final prompt via the prompt renderers (templates) and converted into `messages` objects for the endpoint.

---

## 3. How tools are registered and exposed to models

- Tools are defined in the extension as objects with: name, description, inputSchema (JSON Schema), and an implementation.
  - Example representation (internal):
    {
    name: 'readFile',
    description: 'Read a file from the workspace',
    inputSchema: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] }
    }

- For extension LanguageModel endpoints (vscode.LanguageModelChat) the extension passes an array of tool definitions in the `options.tools` field.
  - Each tool is adapted into an OpenAIFunction-like format (name, description, inputSchema) in the adapter.

- For CAPI endpoints (OpenAI or similar) the tools are passed as `functions` entries on the request body, consistent with the OpenAI function-calling API.
  - createCapiRequestBody or rawMessageToCAPI functions convert the internal prompt + tools into a properly shaped HTTP request body for the endpoint.

- The model is therefore aware of available functions to call, and when a model decides to call a function tool, it emits a function call in the response (either as a function_call property in CAPI, or a LanguageModelToolCallPart in the LanguageModel API).

---

## 4. How model tool calls are represented in responses

- CAPI (OpenAI-style) model response example (synchronous):
  {
  "id":"...",
  "choices":[
  {
  "message":{
  "role":"assistant",
  "content":null,
  "function_call":{
  "name":"readFile",
  "arguments":"{\"path\":\"README.md\"}"
  }
  }
  }
  ]
  }

- Streaming (LanguageModelChat) parts: LanguageModel can stream "toolCall" parts while yielding text parts.
  - The extension's `extChatEndpoint` maps `LanguageModelToolCallPart` into internal `delta.copilotToolCalls` entries.

- The fetcher accumulates the deltas and emits a usable object to the tool calling loop:
  {
  "text": "... some streamed text ...",
  "copilotToolCalls": [ { id, name, arguments } ],
  "thinking": boolean
  }

- The loop inspects `copilotToolCalls`, then invokes the named tool with the parsed arguments.

---

## 5. How the extension invokes tools and re-inserts results

- Tool invocation steps:
  1. The tool-calling loop finds a tool call in the delta.
  2. It finds the tool implementation in the registered tools (via toolsService or registry).
  3. Validates the arguments using the tool's JSON schema (if present).
  4. Runs the tool and returns a tool result object or error.
  5. Adds a special `Tool result` message into the conversation history (Agent Prompt) so the LLM can use that output for the next iteration.
  6. Optionally, the loop continues the conversation (ask model to 'use result and continue') or ends if the model output is final.

- The UI uses `ToolResultElement` to render tool results inline, and an event triggers the tool to be executed if the tool result is not yet present (cached). The UI may show progress and return updates.

---

## 6. Example request and response payloads

Example 1 — CAPI (OpenAI-style) request body with `functions`:

{
"model": "gpt-4o-mini",
"messages": [
{ "role": "system", "content": "You are Copilot." },
{ "role": "user", "content": "Open the file README.md and summarize it." }
],
"functions": [
{
"name": "readFile",
"description": "Read a file from the workspace",
"parameters": {
"type": "object",
"properties": {
"path": { "type": "string", "description": "relative path" }
},
"required": ["path"]
}
}
]
}

Example model response (tool call):

// NOTE: This structure is consistent with official function-calling. The extension maps this into deltas and then into tool call objects.
{
"id": "r1",
"choices": [
{
"message": {
"role": "assistant",
"content": null,
"function_call": {
"name": "readFile",
"arguments": "{ \"path\": \"README.md\" }"
}
}
}
]
}

Once the extension notices the function call, it invokes `readFile` with the parsed arguments and then adds a new assistant message for the result (e.g., "Tool result: content:(lots of text)"), then resumes the model request.

Example 2 — Extension LanguageModelChat request options (vscode LanguageModel API):

// The extension builds a `vscode.LanguageModelChatOptions` payload with `tools`.
{
"vscodeOptions": {
"tools": [
{ "name": "readFile", "description": "Read a file", "inputSchema": { /* JSON Schema */ } }
]
},
"messages": [ /* array of LanguageModelMessage */ ]
}

Streaming model parts include: text parts (text chunks), tool-call parts (name & args), and thinking/data markers. `extChatEndpoint` maps those parts into IResponseDelta objects passed up to the tool-calling loop.

---

## 7. Full annotated sequence (what happens at runtime)

1. User types a prompt and hits submit.
2. Agent builds a prompt (agentPrompt.tsx) including system & user messages.
3. Based on `getAgentTools` and model selection, the extension includes `tools` (functions) in the request payload.
4. The fetcher (chatMLFetcher or extChatEndpoint) sends the request to the model; the response is streamed (parts come in).
5. The stream recorder accumulates text & `copilotToolCalls` when a tool-call appears.
6. The tool-calling loop sees a `copilotToolCall`, validates and runs the tool via toolsService.
7. The tool returns a result (or error), which is added to the conversation as a `Tool result` message.
8. The model may then continue producing more output, now with the tool result in context.
9. Client shows tool results inline in the chat and updates the assistant's reply accordingly.

---

## 8. Relevant files (code pointers)

From the Copilot Chat extension (typical file locations):

- Prompt templates & rendering
  - src/extension/prompts/node/agent/agentPrompt.tsx
  - src/extension/prompts/node/promptTypes/\*.tsx

- Agent intent & tool selection
  - src/extension/intents/node/agentIntent.ts
  - src/extension/intents/node/tools/getAgentTools.ts

- Tool-calling loop & invocation
  - src/extension/intents/node/toolCallingLoop.ts
  - src/extension/prompts/node/panel/toolCalling.tsx
  - src/extension/tools/registry.ts
  - src/extension/tools/\* (tool implementations)

- Networking & ChatML streaming
  - src/platform/chat/common/chatMLFetcher.ts
  - src/extension/agents/node/extChatEndpoint.ts
  - src/platform/networking/common/networking.ts
  - adapters for CAPI & LanguageModel endpoints (various files under extension/endpoint)

- UI & result rendering
  - src/extension/prompts/node/panel/toolCalling.tsx (ToolResultElement)
  - src/extension/ui/\*

- Tests & examples
  - test snapshots showing streamed deltas and tool calls in test fixture snapshots (search for "copilotToolCalls", "ToolCall", "function_call").

---

## 9. Edge cases & important notes

- Not all endpoints support function/tool calls; the extension checks model capabilities and toggles the tool calls.
- Tools may be restricted by security & privacy rules (e.g., disallow file writes outside workspace).
- Tool call argument validation is important (JSON schema enforcement); invalid inputs should be rejected with helpful errors.
- Token budget & summarization can remove some context, so the prompt may be summarized before a call.

---

## 10. Next steps / Where to verify concretely

- Inspect the `createRequestBody` or adapter functions that build request payloads for each endpoint to confirm exact function JSON shape.
- Look up test snapshots or recorded trace logs in repo tests for a real raw request body and model responses with function calls.
- Reproduce an interactive example locally (if using that repo) by enabling a simple tool (readFile) and capturing a stream to observe LanguageModelToolCallPart or function_call behavior.

---

## Appendix: Minimal sample LLM payloads and stream delta shapes

CAPI request body (more explicit):

{
"model": "gpt-4o-mini",
"messages": [
{"role": "system", "content": "Assistant"},
{"role": "user", "content": "List all TODOs in the repo."}
],
"functions": [
{
"name": "listTodosInRepo",
"description": "Return an array of files and TODOs",
"parameters": { "type": "object", "properties": { "glob": { "type": "string" } }, "required": [] }
}
],
"function_call": { "name": "listTodosInRepo" }
}

Streaming delta (internal IResponseDelta):
{
"text": "Processing",
"thinking": false,
"copilotToolCalls": [ { "id": "call-1", "name": "listTodosInRepo", "arguments": { "glob": "**/*.ts" } } ]
}

---

If you want, I can now:

- Add a concrete example payload taken from a recorded test snapshot or generated with the Copilot Chat extension (if you want me to pull those test files now),
- Extract the exact function JSON builders for CAPI vs extension endpoints from the Copilot Chat repo and add to this doc with code snippets and line references.

Tell me which of these you'd like next and I’ll find the code or test examples and add them to this doc.
