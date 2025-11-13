# Copilot Chat Research: How the Agent/Tooling & Streaming Works

This document captures step-by-step research findings about how the agent in the VS Code Copilot Chat extension works — especially the flow of: prompt composition, network requests (makeChatRequest2), the streaming SSE events, how tool calls are detected, validated and invoked, and which files/functions implement them. Findings are recorded iteratively below.

---

## Summary / High-level flow

1. Prompt building (system/user messages) happens via prompt rendering code (PromptRenderer).
2. The prompt is converted into `Raw.ChatMessage[]` using prompt rendering and possibly message converters per provider (e.g., Anthropic conversion to/from Anthropic's block content).
3. The local Language Model server (LanguageModelServer) receives HTTP requests, matches an adapter (e.g., `AnthropicAdapter`), and calls the configured `IChatEndpoint.makeChatRequest2(...)` with streaming callbacks.
4. `makeChatRequest2` is implemented by various endpoints (OpenAI, CAPI, Gemini, etc.) and returns a streaming AsyncIterable via infrastructure implemented in `chatMLFetcher` and `stream` code.
5. Streaming deltas are normalized into `IResponseDelta` objects (see `src/platform/networking/common/fetch.ts`). These deltas may contain `copilotToolCalls`, `beginToolCalls`, `thinking`, `statefulMarker`, `retryReason`, `ipCitations`, `codeVulnAnnotations`, and so on.
6. `ToolCallingLoop` (intents) is the agent orchestration that collects `copilotToolCalls` deltas from streaming responses and executes them via `ToolsService`/`vscode.lm.invokeTool`, then builds the next prompt round and resumes the loop until no tool calls remain or other termination conditions.

## New file: `docs/copilot_chat_research2.md` created and initial content added

This first entry captures these findings and the core files involved.

---

## Key files & responsibilities (quick reference)

- `src/extension/agents/node/langModelServer.ts`
  - Class LanguageModelServer: local HTTP server that routes requests to a protocol adapter and IChatEndpoint.
  - Produces Server-Side Events (SSE) via `adapter.formatStreamResponse` for streaming behavior.

- `src/extension/agents/node/adapters/anthropicAdapter.ts`
  - Example adapter that converts Anthropic client payloads to internal messages and maps streaming blocks (content, tool_usage) into Anthropic SSE event types. Implements `parseRequest`, `formatStreamResponse`, `generateInitialEvents`, and `generateFinalEvents`.

- `src/platform/networking/common/networking.ts`
  - Central networking and request body / header construction logic. Interfaces such as `IChatEndpoint`, `IMakeChatRequestOptions`.

- `src/platform/networking/common/fetch.ts`
  - Defines `IResponseDelta` and related structures. Errors and deltas are normalized here.

- `src/platform/chat/common/chatMLFetcher.ts`
  - Implement `FetchStreamSource` and `FetchStreamRecorder` to manage streaming AsyncIterable responses.

- `src/extension/intents/node/toolCallingLoop.ts`
  - The central loop that handles model responses, collects tool calls, invokes tools, and iterates until there are no more tool calls.

- `src/extension/tools/common/toolsService.ts` and `src/extension/tools/vscode-node/toolsService.ts`
  - Tools registry and invoke pipeline. Validates inputs with AJV and delegates tool invocation.

- `src/extension/prompts/node/base/promptRenderer.ts`
  - Composes prompts (system/user/assistant) and counts tokens. Collapses consecutive system messages. See `renderPromptElement` API.

- `src/extension/byok/common/anthropicMessageConverter.ts`
  - Converts provider-specific messages (Anthropic) into Raw.ChatMessage[] with correct roles and content parts (`tool_use`, `tool_result`, thinking blocks, images, etc.).

- Tools hot path examples (tools implement `ICopilotTool`):
  - `src/extension/tools/node/readFileTool.tsx`
  - `src/extension/tools/node/applyPatchTool.tsx`
  - `src/extension/tools/node/createFileTool.tsx`
  - (many others under `src/extension/tools/node/`)

---

## Deltas and streaming shapes (IResponseDelta fields to look at)

- `text`: streaming text deltas.
- `copilotToolCalls`: tool call objects (e.g., name, arguments, id) found in streaming responses. These are signaled by the model via `{ copilotToolCalls: [...] }` in deltas.
- `beginToolCalls`: marks the start of a tool-call sequence.
- `statefulMarker`: markers used to mark state that needs to be preserved for subsequent prompt rounds.
- `thinking`: incremental model thinking metadata.
- `retryReason` / `codeVulnAnnotations` / `ipCitations` etc. are additional specialized deltas.

Detailed to explore in code: `src/platform/networking/common/fetch.ts` and `responseConvert.ts`.

---

## How tool calling is implemented (high level)

1. Adapter/endpoints produce `IResponseDelta` events containing `copilotToolCalls` or `beginToolCalls`.
2. `ToolCallingLoop` (in `toolCallingLoop.ts`) subscribes to streaming `finishedCb` and collects `copilotToolCalls` into `IToolCall[]` for the current round.
3. `ToolCallingLoop` creates `ToolCallRound` objects recording a round's prompt, response, and any tool calls. If tool calls exist, it then invokes them via `ToolsService.invokeTool`.
4. `ToolsService` validates tool input with AJV (see `validateToolInput`) and maps contributed tool names to actual tool implementations.
5. Tool implementations (e.g., ReadFileTool) are registered via `ToolRegistry.getTools()`; `ICopilotTool` is the tool interface used in `invokeTool`.
6. The results of tool executions can be injected back into the prompt context (as tool result messages) and the loop continues.

---

## Prompt building and system messages

- Prompt rendering uses `PromptRenderer` to render prompt elements and collapse multiple system messages into a single System role message in the final prompt (see `promptRenderer.ts` "Collapse consecutive system messages" logic).
- `anthropicMessageConverter.ts` shows how system messages are collected into `systemMessage.text` and merged.

---

## Next steps

- Add incremental concrete sequences: raw HTTP payloads for a sample Anthropic/OpenAI payload -> adapter parsing -> streaming events -> example `IResponseDelta` JSON -> `ToolCallingLoop` behavior. Include code references and traces.
- Document the exact `IResponseDelta` schema and the types of fields (from `fetch.ts` and `responseConvert.ts`).
- Add example traces from unit tests (e.g., `toolCalling.spec.tsx`, `stream.sseProcessor.spec.ts.snap`) and logging helpers if available.
- Inspect `PromptRenderer` and all agent prompts (prompts folder) to capture the typical system prompt text templates used by the agent.

---

(End of initial findings — will append more detail incrementally.)

---

## Tool call handling — code-level details

1. The `IResponseDelta` emitted during streaming can contain `copilotToolCalls`.

- See `src/platform/networking/common/fetch.ts` for `IResponseDelta` and `ICopilotToolCall` (fields: `name`, `arguments`, `id`).

2. The `ToolCallingLoop` collects `copilotToolCalls` inside the `finishedCb` passed to `makeChatRequest2`.

- See `src/extension/intents/node/toolCallingLoop.ts` for `runOne()` and how `finishedCb` is implemented.
- Key snippet (in `runOne`):
  - `finishedCb` updates the `FetchStreamSource` and pushes tool calls when `delta.copilotToolCalls` is present.
  - Example behavior: tool calls are normalized into `IToolCall[]` and an internal ID is created via `this.createInternalToolCallId(call.id)`.

3. When `ToolCallingLoop` receives a settled `fetch` result, it creates a `ToolCallRound` with `toolCalls` and `statefulMarker` and adds to `this.toolCallRounds`.

- If the `ToolCallRound` contains tool calls, the loop will execute them by invoking `ToolsService`.
- After tools return, their outputs are injected back into the prompt context (typically as Tool messages) and the loop may send a follow-up request to the model.

4. The `ToolsService` validates tool input with AJV schemas and invokes the actual tool (local tool implementations or via `vscode.lm.invokeTool`).

- See `src/extension/tools/common/toolsService.ts` and `src/extension/tools/vscode-node/toolsService.ts`.

5. Tool invocation path example:

- `ToolCallingLoop` executes `ToolsService.invokeTool({ name: 'read_file', arguments: '{...}' })`.
- The `ReadFileTool`'s implementation performs filesystem reads (with telemetry), returns a `LanguageModelToolResult2` containing `content` parts; then `ToolCallingLoop` attaches the tool result to `toolCallResults` and continues the loop.

6. `ToolCallRound` details and post-processing:

- `ToolCallRound.create()` collects the response for that round, tool calls, stateful marker and optional `thinking` metadata.
- This is stored in `this.toolCallRounds[]` and used to form the next prompt's context (e.g., `toolCallResults` is passed in `createPromptContext`).

---

## Prompt conversion, provider adapter & system message merging

1. Prompt building via `PromptRenderer` collects message parts and counts tokens.

- `src/extension/prompts/node/base/promptRenderer.ts` handles prompt assembly and "collapsing" system messages into a single system `Raw.ChatMessage` before sending.

2. Adapters (e.g., `AnthropicAdapter`) convert provider format <-> Raw messages.

- provider->Raw: `anthropicMessagesToRawMessages(messages, systemMessage)` constructs Raw messages (Role: Assistant/Tool/User/System) preserving block types and tool result content mapping.
- Raw->provider: `apiContentToAnthropicContent` and `apiMessageToAnthropicMessage` build provider-specific payloads.
- See `src/extension/byok/common/anthropicMessageConverter.ts` and `src/extension/agents/node/adapters/anthropicAdapter.ts` for details.

3. System messages are merged into a single `system` parameter in some adapters (e.g., Anthropic), and `PromptRenderer` tries to collapse consecutive system messages to avoid sending multiple system messages.

---

## Next actions (what I'll append next)

- Add an example end-to-end test-case: sample prompt -> Anthropic adapter -> streaming SSE events (block start/delta/stop) -> tool_call blocks -> `IResponseDelta` shape -> `ToolCallingLoop` handling -> tool invocation -> resumed prompt.
- Extract example SSE generator events from `anthropicAdapter.ts` and `oaiLanguageModelServer` for sample events.
- Add a sample JSON `IResponseDelta` and the final `ToolCallRound` object structure for a multi-tool sequence.

(More detail will be appended in subsequent iterations.)

---

## Tools invocation — how validation and invocation are wired

1. Validation: `BaseToolsService.validateToolInput` uses AJV to validate the JSON string from the model against the tool input schema.

- If the schema expects an object but the tool input contains nested JSON strings, the validation code attempts to parse nested JSON strings and validate again.
- See `src/extension/tools/common/toolsService.ts` for `validateToolInput` and nested JSON retries.

2. Invocation: `ToolsService` (Vscode implementation `src/extension/tools/vscode-node/toolsService.ts`) delegates `invokeTool` to `vscode.lm.invokeTool(getContributedToolName(name), options, token)`.

- The contributed tool names and mapping are handled via `getContributedToolName` and `mapContributedToolNamesInSchema`.
- See `src/extension/tools/vscode-node/toolsService.ts`.

3. Tool implementations exist both as contributed LM tools (`vscode.lm.tools`) and extension-provided `ICopilotTool` implementations.

- ToolRegistry collects `ICopilotTool` implementations found in `src/extension/tools/node/`.
- For extension-owned tools, `ToolsService.getCopilotTool` returns the `ICopilotTool` to be used in tests or by the ToolsService.

4. Tests and examples: `src/extension/tools/node/test/testToolsService.ts` and `toolCalling.spec.tsx` show how test tool services override tools and how tool results are injected.

---

## Where to find example tests and traces

- `src/extension/tools/node/test/toolCalling.spec.tsx` shows `ToolCallRound` tests, failure handling, and mocked `LanguageModelToolResult` injection into prompts.
- `test/base/extHostContext/simulationExtHostToolsService.ts` is used to simulate extension tools in tests.
- The `MockEndpoint` and `chatMLFetcher` test helpers in `src/platform/endpoint/test/node` and `test/base` provide sample SSE/streaming tests.

(I'll next extract an end-to-end example sequence, using tests and example SSE processor snapshots to show raw events -> deltas -> tool call deltas -> tool invocation.)

---

## Adapter streaming & SSE example (Anthropic)

AnthropicAdapter formats streaming responses as SSE events with block structure. The most common sequence is:

- `message_start` (initial event)
- For text content: `content_block_start` -> `content_block_delta` -> ... -> `content_block_stop`
- For a tool call: `content_block_start` (type: `tool_use`) -> `content_block_delta` (type: `input_json_delta`) -> `content_block_stop`.
- `message_delta` with `stop_reason` (e.g., `'tool_use'` or `'end_turn'`)
- `message_stop`

The adapter's `formatStreamResponse` maps agent `IAgentStreamBlock` values to one or more `IStreamEventData` events. For example:

- If streamData.type === 'text': the adapter emits `content_block_start` (if not started), then `content_block_delta` events with `delta.text`.
- If streamData.type === 'tool_call': it emits `content_block_start` for `tool_use`, a `content_block_delta` with `input_json_delta` containing `partial_json` and `content_block_stop`.

How those events are normalized into `IResponseDelta`:

- `content_block_delta`/text deltas are processed by the `chatMLFetcher`/endpoint layer into `IResponseDelta.text` deltas.
- `tool_use` blocks are translated into `IResponseDelta.copilotToolCalls` with `name`, `arguments`, and `id`.
- `tool_result` blocks (when present) produce `Raw.Tool` messages in `anthropicMessagesToRawMessages` and get represented in downstream code as tool results (e.g., `LanguageModelToolResult2`) that the tool's execution logic may inspect.

Code references:

- `src/extension/agents/node/adapters/anthropicAdapter.ts` — `formatStreamResponse` implementation.
- `src/platform/networking/common/fetch.ts` — `IResponseDelta` and `ICopilotToolCall`.
- `src/extension/byok/common/anthropicMessageConverter.ts` — `anthropicMessagesToRawMessages` maps `tool_use` and `tool_result` blocks to Raw messages.

Example conceptual SSE sequence (abbreviated):

1. message_start
2. content_block_start (index 0) { type: text }
3. content_block_delta (index 0) { delta: "Hello wor" }
4. content_block_delta (index 0) { delta: "ld" }
5. content_block_stop (index 0)
6. content_block_start (index 1) { type: tool_use name: "read_file", id: "call123" }
7. content_block_delta (index 1) { delta: input json } // partial json
8. content_block_stop (index 1)
9. message_delta { delta: { stop_reason: 'tool_use' } }
10. message_stop

This event stream is parsed by the endpoint and converted to incremental deltas of the shape defined in `IResponseDelta`, which are then fed to `ToolCallingLoop`.

---

## Where streaming events are parsed & normalized into IResponseDelta

- `src/platform/endpoint/node/stream.ts` (or similar streaming processors) parse SSE into `ResponsePart` objects and produce `IResponseDelta` objects.
- `src/platform/networking/common/responseConvert.ts` has logic to map provider output events into `IResponseDelta`.

### Example test snapshot (SSEParser) showing tool calls in deltas

Test snapshots show how a model's SSE sequence is parsed into the `finishedCb` chunks and `IResponseDelta`s.
These are available in `src/platform/endpoint/test/node/__snapshots__/stream.sseProcessor.spec.ts.snap` — the snapshot includes `finishedCallback chunks` arrays where deltas include:

- Text deltas as `delta: { text: "..." }` appending to `IResponseDelta.text`.
- `beginToolCalls` to indicate the model announces it will make tool calls (e.g., `{ "beginToolCalls": [{ "name": "copilot_searchCodebase" }] }`).
- `copilotToolCalls`, which list the tool calls with name/arguments/id (e.g.: `{ "name": "copilot_searchCodebase", "arguments": "{\"query\":\"linkedlist\"}", "id": "call_xyz" }`).

This demonstrates: the model can stream partial text, then announce tool calls via `beginToolCalls`, and then provide one or more `copilotToolCalls` deltas that the agent will collect and execute.

Code refs: `src/platform/endpoint/test/node/__snapshots__/stream.sseProcessor.spec.ts.snap` and tests in `src/platform/endpoint/test/node/`.

---

## Tiny contract

- Input: `IMakeChatRequestOptions` containing `messages: Raw.ChatMessage[]`, `requestOptions` (tools/parameters) and the `finishedCb` streaming callback.
- Streaming Output: `IResponseDelta` objects are passed into `finishedCb` repeatedly, each containing partial text, toolCall lists, beginning signals, thinking deltas, or other annotations.
- Error modes: `IResponseDelta.copilotErrors` communicates agent-side errors; `retryReason` signals retryable errors; the fetcher can stop early if `finishedCb` returns a number (stop reading) or if token is canceled; `ToolCallCancelledError` indicates a tool call was cancelled by the runtime.

## Edge cases to watch

- Empty prompt: `buildPromptResult.messages.length === 0` is handled with special logic; fetch is short-circuited.
- Nested JSON as strings in tool arguments: `ToolsService.validateToolInput` attempts to parse nested JSON strings if schema expects objects.
- Tool validation failure: `ToolCallingLoop` emits `ToolFailureEncountered` and may prompt for a retry (tool input or alternative tool).
- Tool invocation limits: `ToolCallingLoop` enforces `toolCallLimit` and has `ToolCallLimitBehavior.Confirm | Stop` options to either prompt for user confirmation or stop if maximum rounds hit.
- Model partial thinking: `delta.thinking` is used to track think-in-progress and then `ThinkingDataItem` is updated with the final fetch result.

---

## Quick references: code paths

- Prompt rendering & tokenization: `src/extension/prompts/node/base/promptRenderer.ts`
- Provider adapter conversions: `src/extension/byok/common/anthropicMessageConverter.ts`, `src/extension/agents/node/adapters/*`
- Server adapter (SSE) & endpoint server: `src/extension/agents/node/langModelServer.ts` — chooses adapter, constructs `finishedCb`, outputs SSE.
- Tool loop orchestration: `src/extension/intents/node/toolCallingLoop.ts` (run => runOne => finishedCb collects copilotToolCalls => ToolCallRound => invokeTools => resume)
- Tools management and invocation: `src/extension/tools/common/toolsService.ts`, `src/extension/tools/vscode-node/toolsService.ts`.

Next: provide an example end-to-end trace using one of the test snapshots in the repo and annotate the mapping to files. Once done, expand the prompt assembly section with exact prompt templates (e.g., `src/extension/prompts/node/panel/*`).

---

## End-to-end example (text -> tool calls -> tool invocation)

1. Prompt build & request

- `ToolCallingLoop.runOne` invokes `this.buildPrompt2(context, ...)` to generate `buildPromptResult.messages` (via `PromptRenderer`).
- `fetch` is called with these messages and a `finishedCb` callback.
- Code: `src/extension/intents/node/toolCallingLoop.ts` (the call to `this.fetch` inside `runOne`).

2. Model streaming SSE -> parsed deltas

- The provider streams partial text using the SSE events (see `AnthropicAdapter.formatStreamResponse`). These text deltas are converted into `IResponseDelta.text` chunks by the endpoint stream processor.
- At some point the model announces a tool-run: `delta.beginToolCalls` followed shortly by `delta.copilotToolCalls` with entries like:
  - { name: "edit*file", arguments: "{...}", id: "tooluse*..." }
- These are visible in `src/platform/endpoint/test/node/__snapshots__/stream.sseProcessor.spec.ts.snap` where a sequence of text deltas is followed by `beginToolCalls` and then `copilotToolCalls`.

3. ToolCallingLoop collects tool calls

- `finishedCb` collects `delta.copilotToolCalls` into the `toolCalls[]` array and tracks `statefulMarker` and `thinking` if present.
- Code reference: `toolCallingLoop.ts` in `runOne`'s `finishedCb` update block (see `if (delta.copilotToolCalls) { toolCalls.push(...)} `).

4. Tools are validated & invoked

- `ToolCallingLoop` takes the `toolCalls` and for each, it calls out to `ToolsService.validateToolInput` to validate arguments according to the tool schema. See `BaseToolsService`'s `validateToolInput` and AJV logic.
- If validation passes, `ToolsService.invokeTool` delegates to `vscode.lm.invokeTool(contributedToolName, options, token)`.
- For extension-owned tools, `ToolsService` maps to `ICopilotTool` implementations.

5. Tool results are returned & injected back into the loop

- The tool result (e.g., `LanguageModelToolResult` with `content` parts) is added to `toolCallResults` which is used to create the next prompt (via `createPromptContext`) in the next loop iteration.
- The `ToolCallRound` records the response & toolCalls and is appended to `this.toolCallRounds`.

6. The agent resumes with a new prompt round if necessary

- The loop iterates and may send the new prompt containing tool results; the model can respond with further text or new tool calls.

Code references for the above flow:

- Prompt build: `src/extension/prompts/node/base/promptRenderer.ts` & `PromptElement` implementations in `src/extension/prompts/node/*`
- SSE & adapter translation: `src/extension/agents/node/adapters/anthropicAdapter.ts`
- Streaming parse & deltas: `src/platform/endpoint/node/stream.ts`, `src/platform/networking/common/fetch.ts` and `src/platform/networking/common/responseConvert.ts`.
- Tool loop aggregation & invocation: `src/extension/intents/node/toolCallingLoop.ts` & `src/extension/tools/*`.
- Tests that illustrate the flow: `src/platform/endpoint/test/node` and `src/extension/tools/node/test/toolCalling.spec.tsx`.

---

## Status & Next steps

- Completed: created initial doc `docs/copilot_chat_research2.md` and added high-level flow, core file references, the IResponseDelta schema, adapter & SSE mapping, sample test snapshot, and the tool invocation path.
- Next: Add example prompt templates and their `system` text (scan `src/extension/prompts/node/panel` and `src/extension/prompts/node/agent`), include a small end-to-end trace fully annotated with the exact code lines for each mapping, and optionally add tests or snippets showing how `vscode.lm.invokeTool` returns `LanguageModelToolResult` to the agent.

If you'd like, I can continue by extracting exact prompt templates & renderers and produce a more detailed end-to-end mapping with code line references and a small sample output that matches a real `sseProcessor` snapshot from the tests.

Next: add a sample trace from tests that show `IResponseDelta` JSON, SSE events mapping, and a multi-tool round with the tool invocation and tool result insertion.
