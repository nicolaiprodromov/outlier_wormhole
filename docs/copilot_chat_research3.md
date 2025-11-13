# Copilot Chat Agent Research (v3)

This document compiles a step-by-step analysis of how the Copilot Chat agent architecture works (as implemented in the `microsoft/vscode-copilot-chat` repository). It focuses on how prompts are assembled, how system/user messages are constructed, how tools are registered and invoked, how SSE streaming and `tool_call`/`function_call` deltas are parsed, and how tool results get fed back into the model.

This research is based on public code and docs examined from the Copilot Chat repository and associated docs. Below you'll find a functional summary, code references, and sanitized payload examples.

## TL;DR

- The agent prompt is composed using a declarative JSX-like prompt builder (`PromptRenderer`) and `AgentPrompt`/`AgentUserMessage` files.
- Tools and functions are made available to the model via the request `functions`/`tools` field in the chat request body; the backend uses OpenAI-style or CAPI-style semantics.
- Streaming SSE responses are parsed for deltas like `text` fragments, `function_call` deltas, `tool_calls` deltas, `beginToolCalls` markers, `thinking` deltas, and `statefulMarker` parts.
- The extension buffers partial tool call deltas, reassembles them, and emits `beginToolCalls` and `copilotToolCalls` events that the UI/intent layer consumes.
- When the extension decides to or is asked to invoke a tool, it calls into the `ToolsService` which uses registered `ICopilotTool` and `ICopilotToolExtension` implementations to resolve inputs and produce results.
- Tool results are then included back into the prompt (as `ToolMessage` in the conversation or as a system-like content block) for the model to ingest, enabling the agent loop to continue.

## Key Files & Responsibilities

- `src/extension/prompts/node/agent/agentPrompt.tsx` — Builds the agent prompt: base system messages, assistant identity and safety rules, `AgentUserMessage` body showing workspace/context and tool references.
- `src/extension/tools/common/toolsRegistry.ts` — Tool registry, tool extension hooks (`resolveInput`, `provideInput`, `filterEdits`), and registration APIs.
- `src/platform/networking/common/networking.ts` — Networking wrappers that set request headers (Authorization, X-Request-Id, OpenAI-Intent, X-Interaction-Type) and create request bodies for the chat/CAPI endpoint.
- `src/extension/prompt/node/chatMLFetcher.ts` — Builds the request body, streams the request to the endpoint, handles retries & filters, and orchestrates response processing.
- `src/platform/networking/node/stream.ts` — SSE stream parser and delta handler that identifies `choice.delta.text`, `choice.delta.function_call`, `choice.delta.tool_calls`, `beginToolCalls`, `thinking`, and `statefulMarker` events. This module emits structured objects used by the UI and intent-handling code.
- `src/extension/prompt/node/panel/toolCalling.tsx` — UI rendering for tool calls and logic to invoke tools. Responsible for feedback, validating tool input, and wiring the tool result back into the conversation.
- `src/extension/conversation/vscode-node/languageModelAccess.ts` — Wraps the server LM APIs for VS Code, maps endpoint types to `IChatEndpoint` calls, converts model output into the extension's internal types.
- `src/extension/intents/node/toolCallingLoop.ts` — The agentic loop above the streaming layer that handles begin->invoke->result->reply cycles.

## High-level Agentic Workflow (Step-by-step)

1. Prompt Composition
   - `AgentPrompt` (via `agentPrompt.tsx`) writes a System message that communicates the assistant's identity and safety rules.
   - It also renders a User message that includes: the user's request, tool references (available tools), workspace context, and any global context or instructions.
   - Prompt builder uses JSX-style elements and `ChatToolCalls` parts to embed tool call history and tool references.

2. Request Construction
   - The fetcher (`chatMLFetcher.ts`) constructs the request body (an OpenAI-like chat/completion request) using the prompt renderer output.
   - Tools and functions are added to the `functions` or `tools` field: this is passed into `OptionalChatRequestParams` and into the request body.
   - Headers are added for `Authorization`, `X-Request-Id`, `OpenAI-Intent`, and `X-Interaction-Type`. An `X-Request-Id` is created per request for telemetry and tracing.

3. Streaming Response
   - The request is made, and the endpoint streams back many SSE events.
   - `stream.ts` parses SSE events and emits deltas:
     - `text` deltas (incremental response content)
     - `function_call` deltas (OpenAI-like function call partials)
     - `tool_calls` deltas (structured tool call(s) the model wants to invoke)
     - `beginToolCalls` marker (model signals it will call one or more tools and isn't returning text yet)
     - `thinking` and `statefulMarker` markers used for UI states
   - Partial tool calls are buffered and assembled by the SSE parser until complete before emitting full structured tool call objects. The SSE parser also emits `beginToolCalls` when appropriate.

4. UI & Intent Layer
   - The UI (`toolCalling.tsx`, panel) or an intents engine subscribes to these events and displays potential tool call requests to the user.
   - If the model requests a tool call, the UI or intents code decides to invoke it (auto-invoke or present to user).

5. Tool Invocation
   - `ToolsService.invokeTool` is used to invoke a registered tool (`ICopilotTool`). The call is passed with a `toolInvocationToken` if present.
   - Before invoking the tool, the extension calls any `ICopilotToolExtension` hook `resolveInput` to let the extension produce or mutate tool inputs (validate or add context) or `provideInput` to prompt the user.
   - `CopilotToolMode` can be PartialContext or FullContext which may determine what input is collected and how the tool is invoked.

6. Tool Result Handling
   - The tool returns a `ToolResult` payload; the extension emits a `ToolMessage` to the conversation. The `ToolMessage` is usually given a `toolCallId` which links it back to the model's `tool_calls` request.
   - The fetcher or conversation layer includes the tool result in the next prompt (either as a message role `assistant`/`tool` or as a content block) for the model to continue.

7. Agent Continuation
   - The model ingests the tool result and either returns an answer or initiates further tool calls and continues the agentic loop.

## Streaming delta examples (Sanitized & illustrative)

SSE payloads use a `choices` array; each choice may include a `delta` object.

Example: partial text deltas

{
"id": "response_1",
"choices": [
{"delta": {"content": "Here is the answer so far..."}}
]
}

Function call delta (OpenAI-like)

{
"id": "response_2",
"choices": [
{
"delta": {
"function_call": {
"name": "search_web",
"arguments": "{\"query\": \"openai plugin\" }"
}
}
}
]
}

Tool calls and beginToolCalls (Copilot-specific tooling):

1. begin tool calls marker

{
"id": "response_3",
"choices": [
{
"delta": {
"beginToolCalls": {
"toolCallIds": ["call1"]
}
}
}
]
}

2. tool call delta (structured)

{
"id": "response_3",
"choices": [
{
"delta": {
"tool_calls": [
{
"id": "call1",
"toolId": "search",
"input": {
"query": "How to handle SSE streams"
},
"metadata": {"toolInvocationToken": "xyz"}
}
]
}
}
]
}

The extension buffers these events, assembles a complete `ICopilotToolCall` object, and emits a `beginToolCalls` then `copilotToolCalls` event for the UI and intent engine.

## Plugging a tool result back into the conversation (Sanitized Example)

Once the tool returns a result (e.g., search results), the extension wraps it into a ToolMessage and adds it to the conversation for the next request:

{
"role": "tool",
"name": "search",
"content": "{...sanitized search results...}",
"toolCallId": "call1"
}

The model receives the tool result and can use it to compose the final answer or to initiate more tool calls. This loops until a final response is produced.

## Example request body (Sanitized & illustrative)

{
"model": "copilot-chat-foo",
"messages": [
{"role": "system", "content": "You are an AI assistant..."},
{"role": "user", "content": "Make a plan for X..."}
],
"functions": [
{
"name": "search",
"description": "Search the web for results",
"parameters": {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}
}
],
"tools": [
{"toolId": "search", "name": "search", "description":"Search the web" }
],
"stream": true
}

Note: The `functions` field is OpenAI function schema; `tools` is the Copilot-specific extension that maps to an in-extension tool definition.

## Headers and Telemetry

- The extension and endpoint wrappers often set the following headers (examples found in `networking.ts` wrappers):
  - `Authorization: Bearer <token>`
  - `X-Request-Id: <uuid>` — unique per request
  - `OpenAI-Intent: <intent>` — indicates type of operation or model intent
  - `X-Interaction-Type` — agent/prompt interaction shape
- These headers help with telemetry, tracing, and routing within the model service platform.

## Important code references to read inside the repo

- Prompt engine & agent user message:
  - `src/extension/prompts/node/agent/agentPrompt.tsx`
  - `src/extension/prompts/node/agent/simpleSummarizedHistoryPrompt.tsx`
  - `src/extension/prompts/node/agent/summarizedConversationHistory.tsx`

- Tool registry & invocation:
  - `src/extension/tools/common/toolsRegistry.ts`
  - `src/extension/prompt/node/panel/toolCalling.tsx`
  - `src/extension/intents/node/toolCallingLoop.ts`

- Streaming & SSE parser:
  - `src/platform/networking/node/stream.ts`
  - `src/platform/networking/common/fetch.ts`
  - `src/extension/prompt/node/chatMLFetcher.ts`

- Endpoint and networking wrappers:
  - `src/platform/networking/common/networking.ts`
  - `src/extension/conversation/vscode-node/languageModelAccess.ts`
  - `src/platform/endpoint/vscode-node/extChatEndpoint.ts`

## Edge cases & implementation details to be aware of

- Some tools are invoked with a `toolInvocationToken`, which allows the tool provider to assert an identity or session context for that invocation.
- Tools can operate in `FullContext` or `PartialContext` modes. PartialContext tools expect specific structured input (for example, a path and file selection), while FullContext tools may be given the whole conversation or a larger context window.
- SSE stream parsing must be careful about partial JSON chunks (the tool `arguments` content may arrive across multiple deltas). The parser buffers and concatenates until the final event to avoid broken JSON parsing.
- The extension uses `resolveInput` / `provideInput` hooks to get user input or to process the call before invoking the tool (example: getting a missing query param from the user).
- Text-only responses and tool call flows must be handled concurrently: the model can generate text and also initiate tool calls — the extension must correctly patch tool messages into the conversation.

## OptionalChatRequest parameters & tools/functions

The chat fetcher uses `OptionalChatRequestParams` to build request bodies. Notable fields:

- `functions?`: OpenAI-style function schema list (name, description, parameters). If included, the model may use `function_call` to indicate it wants to call the function.
- `function_call?`: optionally indicates the name of the function the model should call, or control how the model calls functions.
- `tools?`: Copilot extension tools: an OpenAI-style function tool or a Copilot-specific tool definition (`OpenAiFunctionTool` or `OpenAiResponsesFunctionTool`).
- `tool_choice?`: `'none' | 'auto' | {type: 'function'; function: { name: string } }`. This can drive whether the model should choose to call functions automatically, or not.

Using these fields, `chatMLFetcher.ts` and the endpoint wrappers will populate `program` and `tools` in the body sent to the model backend and consume `tool_calls`/`function_call` deltas as returned by the SSE stream.

## Next Steps (Optional follow-ups)

- Add a sequence diagram: client -> model -> tool -> model to illustrate the full loop.
- Add a sanitized live example with a recorded SSE stream and the exact bytes exchanged (redact API keys).
- Add more code snippets showing how `resolveInput` and `provideInput` hooks are registered and used.

## Source links (useful items from the Copilot Chat repo)

- Agent prompt & renderer: https://github.com/microsoft/vscode-copilot-chat/blob/main/src/extension/prompts/node/agent/agentPrompt.tsx
- Tool calling UI & logic: https://github.com/microsoft/vscode-copilot-chat/blob/main/src/extension/prompts/node/panel/toolCalling.tsx
- Tools registry: https://github.com/microsoft/vscode-copilot-chat/blob/main/src/extension/tools/common/toolsRegistry.ts
- SSE stream parsing: https://github.com/microsoft/vscode-copilot-chat/blob/main/src/platform/networking/node/stream.ts
- Chat fetcher: https://github.com/microsoft/vscode-copilot-chat/blob/main/src/extension/prompt/node/chatMLFetcher.ts
- Networking wrappers: https://github.com/microsoft/vscode-copilot-chat/blob/main/src/platform/networking/common/networking.ts

---

Notes: This file contains a high-level, developer-oriented summary of how Copilot Chat agent mode works and the files to inspect for each portion of the pipeline. If you'd like, I can now expand this document to include exact code references and minimal runnable examples (traces) with sanitized SSE events and matching code-call locations. I can also add a sequence diagram and/or a notebook-style walk-through with a simple local simulation of the SSE parser if that would be helpful.

## Verified delta keys & parser behavior (confirmed in `stream.ts`)

The SSE parser (`SSEProcessor` in `src/platform/networking/node/stream.ts`) watches for and assembles several delta types:

- `choice.delta.content` / `choice.delta.text` — incremental text payloads.
- `choice.delta.function_call` — partial function call (OpenAI style). The model may stream `function_call` name and `arguments` as parts.
- `choice.delta.role == 'function'` and `choice.delta.content` — used for role `function` messages that may be returned by the platform.
- `choice.delta.tool_calls` — an array of tool calls; each `tool_call` has a `id`, `function.name`, and `function.arguments`. These deltas can be partial and are buffered.
- `beginToolCalls` — the parser emits `beginToolCalls` (via `emitSolution`) when the model first starts returning tool calls; this is used to signal the UI to prepare for tool invocation and show `ChatToolCalls` elements.
- `FinishedCompletionReason.ToolCalls` & `FinishedCompletionReason.FunctionCall` — the SSE parser maps these finish reasons and yields a `FinishedCompletion` object (via `emitSolution`), including `toolCalls` or `functionCalls` arrays.

Parser behavior highlights:

- The parser maintains in-memory buffers for functionCall partials and toolCalls partials. These partials accumulate until the finish reason indicates a call is complete.
- When a `tool_calls` delta arrives, if it's the first tool in the stream for the solution and the `solution.text` already contains text, the parser will flush the text and emit `beginToolCalls` specifying the first tool's name.
- The code supports both the `function_call` pattern (OpenAI) and the `tool_calls` pattern (Copilot-specific) and will co-exist in streams.
- The parser yields a `FinishedCompletion` with a `reason` set appropriately: e.g., `ToolCalls` or `FunctionCall`.

## Where tool calls/writes get emitted to the UI

- The SSE parser yields `FinishedCompletion` objects with `copilotToolCalls` or `toolCalls` copy contained in the payload (structure `ICopilotToolCall[]` in the codebase). The UI and the tool-calling loop detect these and render `ChatToolCalls`.
- `ChatToolCalls` will display the tool call rounds and provides UI affordances (e.g., `Invoke`, `Edit`, `Cancel`) which call `toolsService.invokeTool` or `resolveInput` for user-supplied inputs.

## Follow-ups implemented and future additions

I added a new section describing SSE delta keys and parser behavior. Next I can:

- Add a sequence diagram to visualize the full lifecycle (prompt build -> request -> SSE stream -> tool call -> tool invocation -> model --> final answer).
- Add a sanitized live example with a recorded SSE stream and the exact bytes exchanged (redact API keys).
- Add a short sample test scaffolding that simulates an open streaming response and how the `SSEProcessor` processes a tool call.

If you'd like any of the follow-ups (sequence diagram, trace, sample test), tell me which you'd prefer first and I'll add it to this document next.
