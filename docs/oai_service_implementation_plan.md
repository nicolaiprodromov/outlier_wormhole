# OAI Service Implementation Plan

## Making the OpenAI-Compatible Server Work with VSCode Copilot Chat

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current Architecture Analysis](#current-architecture)
3. [Gap Analysis](#gap-analysis)
4. [Prompt Injection Strategy](#prompt-injection)
5. [Tool Calling Response Format](#tool-calling-format)
6. [Tool Result Handling](#tool-result-handling)
7. [Step-by-Step Implementation Plan](#implementation-steps)
8. [Testing Strategy](#testing-strategy)
9. [Risk Assessment](#risk-assessment)

---

## 1. Executive Summary {#executive-summary}

**Objective**: Modify the OAI service (`/services/oai`) to correctly emulate VSCode Copilot Chat's expected behavior when acting as an OpenAI-compatible endpoint.

**Key Constraint**: The Outlier platform ignores system prompts on their server side, requiring us to inject all system content into user prompts.

**Expected Outcome**: VSCode Copilot Chat clients can connect to our OAI service and receive properly formatted streaming responses with correct tool calling behavior that maximizes agent effectiveness.

---

## 2. Current Architecture Analysis {#current-architecture}

### 2.1 Main Entry Point: wormhole-oai.py

**Endpoint**: `POST /v1/chat/completions`

The main entry point accepts OpenAI-compatible chat completion requests with the following flow:

```mermaid
graph TD
    A[Client Request] --> B[Authentication Middleware]
    B --> C[/v1/chat/completions Handler]
    C --> D{Parse Request Body}
    D --> E[Extract messages by role]
    E --> F{Message Processing}
    F --> G[Extract system message]
    F --> H[Extract user message]
    F --> I[Extract tool results]
    F --> J[Detect conversation state]
    J --> K{Conversation Type?}
    K -->|New with tools| L[handle_initial_tool_request]
    K -->|Tool response| M[handle_tool_response]
    K -->|Simple message| N[handle_simple_user_message]
    L --> O[AgentWorkflow Processing]
    M --> O
    N --> O
    O --> P{Stream?}
    P -->|Yes| Q[SSE Streaming Response]
    P -->|No| R[JSON Response]
```

**Key Request Processing Logic** (lines 252-299):

1. **Message Role Parsing**: Iterates through all messages and separates by role:
   - `system`: Stores in `raw_system`, extracts `<context>` tags
   - `user`: Stores in `raw_user`, extracts `<context>`, `<attachments>`, and `<userRequest>` tags
   - `assistant`: Checks for final answer markers using `agent_workflow.has_final_answer_marker()`
   - `tool`: Sets `has_tool_results = True` flag

2. **Conversation State Detection** (lines 301-309):
   - Checks if any assistant messages exist to determine if new conversation
   - Resets `active_conversation_id` for new conversations
   - Maintains conversation ID for continuing conversations

3. **Request Routing** (lines 311-348):
   - **New tool request**: `tools` exist AND no tool results OR last assistant had final answer
     - Calls: `agent_workflow.handle_initial_tool_request()`
   - **Tool response**: `has_tool_results = True` AND last assistant didn't have final answer
     - Calls: `agent_workflow.handle_tool_response()`
   - **Simple message**: No tools or conversation continuation
     - Calls: `agent_workflow.handle_simple_user_message()`

4. **Response Generation** (lines 350-430):
   - Generates `completion_id` and timestamp
   - **Streaming mode** (lines 353-404):
     - Yields role delta first
     - Yields tool calls as complete chunks (NOT incremental)
     - Yields text content character-by-character
     - Yields final chunk with `finish_reason`
     - Yields `data: [DONE]`
   - **Non-streaming mode** (lines 405-430):
     - Returns complete JSON response with message and usage stats

### 2.2 AgentWorkflow: Conversation and Tool Management

**File**: `agent_workflow.py`

#### 2.2.1 Conversation Management

**Function**: `get_or_create_conversation()` (lines 23-52)

- Checks if conversation ID exists in cache via callback
- If not, creates new conversation using `send_script_async("create_conversation.js")`
- Caches conversation ID globally using `set_conversation_id` callback
- Returns both conversation ID and initial response if created

**Function**: `send_to_outlier()` (lines 54-84)

- Sends prompt to Outlier platform via `send_script_async("send_message.js")`
- Passes: `conversationId`, `prompt`, `model`, `systemMessage`
- **Critical Issue**: System message is sent but Outlier ignores it
- Logs conversation data via callback to data folder
- Returns response text and parsed result

#### 2.2.2 Tool Call Parsing

**Function**: `parse_tool_call()` (lines 86-108)

- Searches for XML-style invoke pattern: `<invoke name="tool_name">...</invoke>`
- Extracts parameters using nested pattern: `<parameter name="param_name">value</parameter>`
- Constructs OpenAI-compatible tool call format:
  ```python
  {
      "id": "call_{24_char_hex}",
      "type": "function",
      "function": {
          "name": "tool_name",
          "arguments": "{json_string}"
      }
  }
  ```
- Returns cleaned text (with invoke tags removed) and tool call object
- Returns `(None, None)` if no tool call found

#### 2.2.3 Tool Response Handling

**Function**: `handle_tool_response()` (lines 176-236)

- **Input**: Model, full message array, raw system prompt
- **Process**:
  1. Extracts context from `raw_system` using `extract_context_tag()`
  2. Finds last assistant message with tool calls
  3. Collects all tool messages that follow
  4. Builds tool output string combining:
     - Tool call description: "You called: tool_name(args)"
     - Tool results: "Tool 'tool_name' returned: content"
  5. Composes prompt using `composer.compose_tool_response(tool_output, context)`
  6. Sends to Outlier and parses response
  7. Checks for final answer or additional tool calls

**Key Issue**: Context from system prompt is extracted but system prompt itself is discarded by Outlier

#### 2.2.4 Final Answer Extraction

**Function**: `extract_final_answer()` (lines 110-127)

- Searches for multiple patterns:
  1. `<invoke name="final_answer"><parameter name="answer">...</parameter></invoke>`
  2. `<final_answer>...</final_answer>`
  3. Fallback: Removes markers and returns cleaned text
- Returns extracted answer string

**Function**: `has_final_answer_marker()` (lines 129-134)

- Checks if response contains final answer indicators:
  - `name="final_answer"` substring
  - `<final_answer>` tag (case-insensitive)
- Used to determine if agent is done with task

#### 2.2.5 Request Handlers

**Function**: `handle_initial_tool_request()` (lines 168-286)

- Extracts custom instructions from `raw_system` using `extract_client_instructions()`
- Calls `initialize_system_prompt()` with tools, attachments, context, custom instructions
- Gets system message from composer (stored but not used by Outlier)
- Creates or gets conversation
- Processes first response for tool calls or final answer
- Returns: `(clean_text, tool_calls, conversation_id)`

**Function**: `handle_simple_user_message()` (lines 238-286)

- Extracts context from raw system
- Composes simple user prompt using `composer.compose_simple_user()`
- Creates or gets conversation
- Sends to Outlier and returns response
- No tool call parsing (expects plain text response)

### 2.3 TemplateComposer: Prompt Construction

**File**: `template_composer.py`

#### 2.3.1 Template Loading

**Constructor** (lines 8-13):

- Loads YAML templates from `agent_prompts.yaml`
- Initializes templates directory path
- Caches system prompt

**Function**: `get_system()` (lines 20-27)

- Loads `templates/system.mdx` file
- Caches content in `_system_cache`
- Returns system prompt string
- **Critical**: This is sent to Outlier but ignored

#### 2.3.2 Prompt Composition

**Function**: `initialize_system_prompt()` (lines 29-63)

- **Purpose**: Builds initial prompt with tools for new requests - **THIS IS THE SYSTEM PROMPT INJECTION MECHANISM**
- **Process**:
  1. Converts tools to two formats:
     - Full format: `to_tool_calling_prompt()` → "- name: description"
     - Simple format: `to_simple_tool_prompt()` → "- name(param: type, ...)"
  2. Builds variables dict with:
     - `system_content`: From `system.mdx` - **INJECTED INTO PROMPT**
     - `tools`: Full tool descriptions - **INJECTED INTO PROMPT**
     - `simple_tools`: Simple tool signatures
     - `managed_agents`: Not currently used
     - `custom_instructions`: Extracted from VSCode system prompt - **INJECTED INTO PROMPT**
     - `rules`: From `templates/rules.mdx` - **INJECTED INTO PROMPT**
     - `attachments`: File attachments from request
     - `context`: Workspace context - **INJECTED INTO PROMPT**
     - `user_request`: The actual task
  3. Selects template:
     - `first_system_prompt` if `is_first=True`
     - `system_prompt` if continuing conversation
  4. Renders template using Jinja2 via `populate_template()`
- **Note**: This function effectively injects all system content into the user prompt sent to Outlier

**Function**: `compose_tool_response()` (lines 65-73)

- **Purpose**: Builds prompt after tool execution
- **Template**: `tool_response` from YAML
- **Variables**:
  - `system_content`: System prompt (not used by Outlier)
  - `tool_output`: Combined tool call description + results
  - `context`: Workspace context
- **Output**: Formatted prompt asking for next step or final answer

**Function**: `compose_simple_user()` (lines 75-89)

- **Purpose**: Builds prompt for non-tool requests
- **Template**: `first_simple_user` if first message, else `simple_user`
- **Variables**:
  - `system`: System prompt content
  - `attachments`: File attachments
  - `context`: Workspace context
  - `user_request`: User's message
- **Usage**: For conversational messages without tool calling

### 2.4 Prompt Templates: agent_prompts.yaml

#### 2.4.1 System Prompt Templates

**Template**: `first_system_prompt` (lines 34-70)

- **Structure**:
  ```
  {system_content from system.mdx}
  ---
  Tool calling instructions
  ---
  {Full tool descriptions with parameters}
  ---
  {custom_instructions from VSCode}
  ---
  {rules from rules.mdx}
  ---
  {attachments}
  ---
  {context}
  ---
  Task: {user_request}
  ```
- **Key Feature**: Includes full `system_content` at the top
- **Tool Format**: Shows complete tool XML syntax

**Template**: `system_prompt` (lines 1-32)

- **Structure**: Similar but uses `simple_tools` instead of full `tools`
- **Difference**: More concise, assumes tools already introduced
- **No system_content**: Doesn't repeat the system.mdx content

#### 2.4.2 Tool Response Template

**Template**: `tool_response` (lines 154-167)

- **Purpose**: Prompt sent after tool execution
- **Structure**:
  ```
  {context if exists}
  ---
  {tool_output}
  ---
  Now provide your final answer or call another tool if needed.
  If this is your final answer, use:
  <invoke name="final_answer">
  <parameter name="answer">your answer here</parameter>
  </invoke>
  ```
- **Explicit Instruction**: Shows agent how to signal completion

#### 2.4.3 Simple User Templates

**Template**: `first_simple_user` (lines 185-202)

- Includes system prompt at top for first message
- Then attachments, context, and user request

**Template**: `simple_user` (lines 169-183)

- No system prompt
- Just attachments, context, and user request

### 2.5 Prompt Utilities: prompt_utils.py

#### 2.5.1 Extraction Functions

**Function**: `extract_client_instructions()` (lines 5-17)

- Extracts last occurrence of `<instructions>...</instructions>` tag from system prompt
- Uses regex with `DOTALL` flag to capture multi-line content
- Returns empty string if not found
- **Purpose**: Capture VSCode Copilot's instructions to agent

**Function**: `extract_context_tag()` (lines 20-30)

- Extracts `<context>...</context>` tag from system prompt
- Returns empty string if not found
- **Purpose**: Preserve workspace context across requests

#### 2.5.2 Tool Formatting Functions

**Function**: `to_tool_calling_prompt()` (lines 38-42)

- **Input**: OpenAI tool schema
- **Output**: `"- {name}: {description}"`
- **Purpose**: Simple one-line tool description

**Function**: `to_simple_tool_prompt()` (lines 45-58)

- **Input**: OpenAI tool schema
- **Output**: `"- {name}({param1: type1, param2: type2})"`
- **Purpose**: Function signature style tool description

**Function**: `to_code_prompt()` (lines 61-77)

- **Input**: OpenAI tool schema
- **Output**: Python function definition with docstring
- **Purpose**: Code-style tool description (not currently used)

#### 2.5.3 Template Rendering

**Function**: `populate_template()` (lines 33-35)

- Uses Jinja2 with `StrictUndefined` mode
- Raises exception on missing variables
- **Purpose**: Safe template rendering with error handling

### 2.6 Current Streaming Implementation

**Location**: `wormhole-oai.py`, lines 353-404

#### 2.6.1 SSE Stream Format

The streaming response follows OpenAI's Server-Sent Events format:

1. **First Chunk** (lines 356-368):

   ```python
   {
       "id": chunk_id,
       "object": "chat.completion.chunk",
       "created": timestamp,
       "model": model,
       "choices": [{
           "index": 0,
           "delta": {"role": "assistant"},
           "finish_reason": None
       }]
   }
   ```

2. **Tool Call Chunks** (lines 370-383):
   - **Issue**: Sends complete tool call in single chunk
   - **Current Format**:
     ```python
     "delta": {"tool_calls": [complete_tool_call_object]}
     ```
   - **VSCode Expectation**: Incremental chunks with indices

3. **Text Content Chunks** (lines 385-397):
   - Sends one character at a time
   - Each chunk contains `"delta": {"content": "single_char"}`
   - Correct format for text streaming

4. **Final Chunk** (lines 399-411):
   - Empty delta: `"delta": {}`
   - Sets `finish_reason`: `"tool_calls"` if tools, else `"stop"`
   - Correct format

5. **Stream Terminator** (line 412):
   - Sends `"data: [DONE]\n\n"`
   - Correct format

### 2.7 What Currently Works ✓

1. **Authentication**: API key validation middleware works correctly
2. **Model Listing**: `/v1/models` returns proper model list
3. **Message Parsing**: Successfully extracts role-based messages
4. **Conversation State**: Correctly detects new vs continuing conversations
5. **Context Extraction**: Properly extracts `<context>` and `<attachments>` tags
6. **Tool Call Parsing**: Successfully parses XML-style invoke tags into OpenAI format
7. **Final Answer Detection**: Reliably identifies when agent is done
8. **Text Streaming**: Character-by-character streaming works correctly
9. **SSE Format**: Basic SSE structure is correct
10. **Tool Composition**: Converts OpenAI tool schemas to readable formats
11. **Template System**: Jinja2 rendering works reliably
12. **Conversation Logging**: Data folder logging captures all exchanges

### 2.8 What Doesn't Work ✗

#### 2.8.1 Critical Issues

1. **System Prompt Ignored by Outlier (ALREADY ADDRESSED)**
   - **Location**: `agent_workflow.py`, `send_to_outlier()` line 58
   - **Issue**: `systemMessage` parameter is sent but Outlier platform ignores it
   - **Solution**: System content is ALREADY injected into prompts via template system (`template_composer.py`)
   - **Status**: ✅ Working - Agent receives all system instructions, tool descriptions, and rules through templates
   - **Redundancy**: Smaller system message also sent for future-proofing/research

2. **Tool Call Streaming Format**
   - **Location**: `wormhole-oai.py`, lines 370-383
   - **Issue**: Sends complete tool call in one chunk
   - **Expected**: Incremental streaming with `index` field:
     ```python
     # Chunk 1: Function name
     {"tool_calls": [{"index": 0, "function": {"name": "tool_name"}}]}
     # Chunk 2: Arguments start
     {"tool_calls": [{"index": 0, "function": {"arguments": "{"}}]}
     # Chunk 3: Arguments continue
     {"tool_calls": [{"index": 0, "function": {"arguments": "\"param\""}}]}
     # etc.
     ```
   - **Impact**: VSCode may not correctly handle non-incremental tool calls

3. **System Prompt Injection Strategy Missing**
   - **Issue**: No mechanism to inject system prompt into first user message
   - **Required**: Must prepend system content to user prompt for Outlier
   - **Complexity**: Must happen only on first message of new conversation
   - **Impact**: Agent doesn't receive proper instructions

#### 2.8.2 Moderate Issues

4. **Tool Call ID Generation**
   - **Location**: `agent_workflow.py`, line 100
   - **Issue**: Uses `uuid.uuid4().hex[:24]` for tool call IDs
   - **Expected**: OpenAI uses pattern `call_{28_chars}` total
   - **Impact**: Minor, but IDs don't match OpenAI format exactly

5. **Context Handling Inconsistency**
   - **Issue**: Context extracted from both system and user messages
   - **Current Logic**: Checks system first, then user if not found
   - **Problem**: If context in both, only system version used
   - **Impact**: May lose context updates in conversation

6. **Template Selection Logic**
   - **Location**: `template_composer.py`, `initialize_system_prompt()` line 58
   - **Issue**: Uses `is_first` flag but conversation state is complex
   - **Problem**: "First" means first in conversation, but system prompt changes
   - **Impact**: May use wrong template for continuation messages

#### 2.8.3 Minor Issues

7. **Rules File Loading**
   - **Location**: `agent_workflow.py`, line 139
   - **Issue**: Loads `templates/rules.mdx` but doesn't check if exists
   - **Impact**: May fail if rules file missing (though has fallback to empty string)

8. **Error Handling in Streaming**
   - **Location**: `wormhole-oai.py`, SSE generator
   - **Issue**: No try-catch around stream generation
   - **Impact**: Exceptions may break stream without proper termination

9. **Usage Token Calculation**
   - **Location**: `wormhole-oai.py`, lines 414-415
   - **Issue**: Simple word count for token estimation
   - **Impact**: Inaccurate token usage reporting (not critical)

10. **Max Steps Tracking**
    - **Location**: `agent_workflow.py`, lines 148-153
    - **Issue**: `step()` function defined but never called
    - **Impact**: No actual step limiting in agent loop

### 2.9 Architecture Strengths

1. **Modular Design**: Clear separation between endpoint, workflow, and templating
2. **Template System**: YAML-based templates are easy to modify
3. **Conversation Persistence**: Proper conversation ID management
4. **Logging Infrastructure**: Comprehensive logging to data folder
5. **Flexible Tool Parsing**: Handles multiple tool call formats
6. **Clean Abstractions**: Callbacks for conversation management

### 2.10 Architecture Weaknesses

1. **Tight Coupling to Outlier**: Directly depends on Outlier platform behavior
2. **No Retry Logic**: Single attempt for Outlier API calls
3. **Global State**: Uses global `active_conversation_id` variable
4. **Limited Error Recovery**: Minimal fallback mechanisms
5. **Template Complexity**: Multiple similar templates increase maintenance burden
6. **No Caching**: Re-processes tools and templates on every request

---

## 3. Gap Analysis {#gap-analysis}

This section identifies all discrepancies between VSCode Copilot Chat's expectations (documented in `vscode_copilot_workflow_final.md`) and our OAI service's current implementation (analyzed in Section 2). Each gap is categorized by priority and linked to implementation sections that address it.

### 3.1 Critical Gaps (Must Fix for Basic Functionality)

These gaps will prevent VSCode Copilot Chat from working at all or cause complete failure of the agentic workflow.

#### Gap 3.1.1: System Prompt Ignored by Outlier Platform (ALREADY ADDRESSED)

**What VSCode Expects**:

- System messages contain crucial instructions, tool definitions, workspace context, content policies
- System messages processed before user message to establish agent identity and capabilities
- Multiple system messages supported (identity, context, experiment flags)
- Example system content:

  ```
  You are Copilot, an AI coding assistant. You help developers write, understand, and improve code.

  Follow Microsoft content policies. Avoid harmful content.

  Use tools by invoking: <invoke name="tool_name">...</invoke>
  ```

**What Our Service Currently Does**:

- **Injects all system content into prompts** via the template system (`template_composer.py`)
- Templates automatically include system instructions, tool definitions, and context
- Additionally sends a smaller redundant `systemMessage` parameter (ignored by Outlier, for future-proofing)
- Agent successfully receives identity, instructions, tool definitions, and workspace context

**Why This Approach Works**:

- ✅ Agent has identity ("You are Copilot...")
- ✅ Tool calling instructions included (invoke syntax, XML format)
- ✅ Safety guardrails and content policies present
- ✅ Workspace awareness (files, git status, open editors)
- ✅ Agent behavior is consistent and predictable
- ✅ **TOOL CALLING FUNCTIONALITY WORKS**

**Current Status**: ✅ **ALREADY IMPLEMENTED** - System content injection working via templates

**Implementation**: [Section 4: Prompt Injection Strategy](#prompt-injection) documents the current approach:

- System content included in prompts via template rendering
- Smaller redundant system message sent for future-proofing
- Works for both new and continuing conversations
- Preserves all original message structure

---

#### Gap 3.1.2: Tool Call Streaming Format Incorrect

**What VSCode Expects**:

- **Incremental tool call streaming** with proper delta structure
- Tool calls must include `index` field for buffering
- Arguments streamed separately from tool call metadata
- Specific delta sequence:
  1. **Start Delta**: `{"tool_calls": [{"index": 0, "id": "call_xyz", "type": "function", "function": {"name": "read_file", "arguments": ""}}]}`
  2. **Arguments Delta**: `{"tool_calls": [{"index": 0, "function": {"arguments": "{\"path\":"}}]}`
  3. **More Arguments**: `{"tool_calls": [{"index": 0, "function": {"arguments": "\"README.md\"}"}}]}`
  4. **Final Arguments**: `{"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}`

**What Our Service Currently Does** (lines 370-383 in `wormhole-oai.py`):

- Sends **complete tool call object in single chunk**
- No `index` field in tool call object
- Arguments are complete JSON, not streamed
- Current format:
  ```python
  "delta": {"tool_calls": [complete_tool_call_object]}  # WRONG
  ```

**Why This Matters**:

- VSCode's SSEProcessor expects incremental streaming for proper buffering
- Without `index` field, VSCode cannot track multiple tool calls correctly
- Parser may fail to detect `beginToolCalls` transition
- Tool calls may not assemble correctly from deltas
- Multi-tool responses completely broken
- **BLOCKS RELIABLE TOOL CALLING**

**Current Impact**: 🔴 **CRITICAL - Tool calling unreliable or broken**

**Implementation Section**: [Section 5: Tool Calling Response Format](#tool-calling-format)

- Implement incremental tool call streaming
- Add `index` field to track tool call position
- Split into start delta (id, type, name) + arguments deltas
- Support multiple tool calls with sequential indices

---

#### Gap 3.1.3: Multiple Tool Calls NOT Supported (CURRENT LIMITATION)

**What VSCode Expects**:

- Agent can call multiple tools in single response
- Each tool call has unique ID and index
- Example: Read file + Edit file in one turn
- All tool calls must be detected and parsed

**What Our Service Currently Does** (`agent_workflow.py`, `parse_tool_call()` lines 86-108):

- ❌ **ONLY PARSES FIRST TOOL CALL** from response
- ❌ Returns single tool call OR None (NOT a list)
- ❌ Subsequent `<invoke>` blocks completely ignored
- ❌ **THIS IS A CRITICAL LIMITATION**
- Logic:
  ```python
  invoke_match = re.search(r'<invoke name="([^"]+)">', text)  # Only finds first match
  if invoke_match:
      return (cleaned_text, single_tool_call)  # Single object, not list
  ```

**Why This Matters**:

- ❌ Multi-step tasks requiring multiple tools FAIL
- ❌ Example: "Read README and create summary" needs 2 tools - only first executes, second is lost
- ❌ Agent workflow breaks on complex tasks
- ❌ **BLOCKS MULTI-STEP AGENTIC TASKS COMPLETELY**

**Current Impact**: 🔴 **CRITICAL - NOT IMPLEMENTED - Complex tasks fail**

**Implementation Section**: [Section 5: Tool Calling Response Format](#tool-calling-format)

- **BUILD FROM SCRATCH**: Create new `parse_all_tool_calls()` function
- Use `re.finditer()` instead of `re.search()` to find ALL matches
- Return list of tool calls instead of single object
- Update all callers to handle lists
- This is NEW functionality that does NOT exist yet

---

### 3.2 High Priority Gaps (Breaks Advanced Features)

These gaps prevent advanced agent capabilities but allow basic functionality to work.

#### Gap 3.2.1: Tool Result Correlation is Order-Based, Not ID-Based

**What VSCode Expects**:

- Tool results linked to tool calls via `tool_call_id`
- Explicit ID matching: `{"role": "tool", "tool_call_id": "call_abc123", "content": "..."}`
- Robust against missing results or out-of-order delivery
- Validates that all tool calls received results

**What Our Service Currently Does** (`handle_tool_response()` lines 176-236):

- Assumes order-based matching
- Collects tool results sequentially after assistant message
- No validation of `tool_call_id` linkage
- No detection of missing/extra results
- Logic:
  ```python
  for msg in messages:
      if msg.get("role") == "tool":
          tool_output_parts.append(f"Tool '{msg['name']}' returned: {msg['content']}")
  ```

**Why This Matters**:

- Order-based matching fragile (breaks if results out of order)
- No error detection for missing results
- Can't handle partial tool execution failures
- Agent gets confused with incomplete/wrong data
- **REDUCES RELIABILITY**

**Current Impact**: 🟡 **HIGH - Reliability issues with tool results**

**Implementation Section**: [Section 6: Tool Result Handling](#tool-result-handling)

- Build `tool_calls_map` by ID from assistant message
- Build `tool_results_map` by `tool_call_id` from tool messages
- Match results to calls explicitly by ID
- Detect and handle missing/extra results

---

#### Gap 3.2.2: Tool Result Formatting Lacks Status Indicators

**What VSCode Expects**:

- Clear indication of tool success vs failure
- Structured formatting for multiple tool results
- Easy for LLM to parse and understand outcomes

**What Our Service Currently Does**:

- Simple format: `"Tool 'read_file' returned: [content]"`
- No success/error indication
- No separation between tool call description and result
- All results look identical regardless of outcome

**Why This Matters**:

- Agent can't distinguish successful vs failed tool execution
- May continue with broken assumptions
- Poor prompt structure reduces agent effectiveness
- **REDUCES AGENT INTELLIGENCE**

**Current Impact**: 🟡 **HIGH - Reduced agent quality**

**Implementation Section**: [Section 6: Tool Result Handling](#tool-result-handling)

- Add status indicators: `[✓ SUCCESS]` or `[✗ ERROR]`
- Include tool call description before result
- Format: `"Tool Call: read_file({args})\nResult [✓ SUCCESS]: [content]"`
- Detect errors by checking for "Error:" prefix in content

---

#### Gap 3.2.3: No Support for Text Before Tool Calls

**What VSCode Expects**:

- Agent can provide explanatory text BEFORE calling tools
- Example: "I'll read the file for you" → then tool call
- Text streaming happens first, then tool call streaming
- `beginToolCalls` marker signals transition from text to tools

**What Our Service Currently Does** (lines 385-397 in `wormhole-oai.py`):

- ❌ **Does NOT support text before tool calls**
- When tool calls are present, you NEVER see any text content
- The parsing logic separates text and tool calls, but only one is emitted
- If response contains tool calls, the text portion is discarded or not generated

**Why This Matters**:

- Agent cannot provide explanatory context before executing tools
- Poor UX - user doesn't know what agent is planning to do
- Reduces agent's ability to communicate intent
- **REDUCES TRANSPARENCY AND USER EXPERIENCE**

**Current Impact**: 🟡 **HIGH - Missing feature, reduced UX**

**Implementation Section**: Section 5 - Need to support mixed text+tool responses

---

#### Gap 3.2.4: SSE Stream Structure Correct, But Tool Streaming Wrong

**What VSCode Expects**:

- Basic SSE structure: `data: {json}\n\n`
- Role delta first
- Content/tool deltas incrementally
- Final chunk with `finish_reason`
- Stream terminator: `data: [DONE]\n\n`

**What Our Service Currently Does**:

- ✅ Role delta correct (line 356-368)
- ✅ Text streaming correct (line 385-397)
- ✅ Completion delta correct (line 399-411)
- ✅ Stream terminator correct (line 412)
- ❌ Tool call deltas WRONG (line 370-383) - see Gap 3.1.2

**Why This Matters**:

- Most of SSE structure is correct
- Only tool call portion needs fixing
- Foundation is solid, just one component broken

**Current Impact**: 🟡 **HIGH - Partial implementation**

**Implementation Section**: [Section 5: Tool Calling Response Format](#tool-calling-format)

- Only need to fix tool call delta section
- Keep existing text, role, completion, terminator code
- Replace lines 370-383 with proper incremental tool streaming

---

### 3.3 Medium Priority Gaps (Quality & Robustness)

These gaps affect code quality, maintainability, and edge case handling but don't block core functionality.

#### Gap 3.3.1: Tool Call ID Format Doesn't Match OpenAI

**What VSCode Expects**:

- OpenAI format: `call_{28_chars}` total length
- Example: `call_abc123def456ghi789jkl012`

**What Our Service Currently Does** (`parse_tool_call()` line 100):

- Uses: `call_{24_hex_chars}` total 29 chars
- Logic: `f"call_{uuid.uuid4().hex[:24]}"`
- Close but not exact match

**Why This Matters**:

- Minor cosmetic difference
- Doesn't affect functionality (IDs still unique)
- VSCode doesn't validate ID format strictly
- **LOW PRIORITY COSMETIC ISSUE**

**Current Impact**: 🟢 **MEDIUM - Cosmetic only**

**Implementation Section**: Section 5 (minor fix)

- Change `[:24]` to `[:27]` to get 32 total chars (or use `[:23]` for 28 total)
- Optional improvement, not critical

---

#### Gap 3.3.2: No Validation of Tool Call ID Presence

**What VSCode Expects**:

- Every tool call MUST have unique `id` field
- Used for tracking and result correlation

**What Our Service Currently Does**:

- Always generates ID with `uuid.uuid4()` - guaranteed unique
- ✅ ID always present
- But no explicit validation

**Why This Matters**:

- Current implementation already correct
- Adding validation adds robustness
- Defensive programming best practice

**Current Impact**: 🟢 **MEDIUM - Already works, could add validation**

**Implementation Section**: Section 5 (optional enhancement)

- Add assertion that ID exists before returning tool call
- Log warning if ID generation fails

---

#### Gap 3.3.3: Error Handling in SSE Generator Missing

**What VSCode Expects**:

- Graceful error handling in streaming
- Proper stream termination even on errors

**What Our Service Currently Does** (`wormhole-oai.py` lines 353-404):

- No try-catch around stream generation
- Exceptions may break stream without `[DONE]`
- Could leave VSCode parser in inconsistent state

**Why This Matters**:

- Exceptions cause incomplete streams
- VSCode hangs waiting for `[DONE]`
- Poor user experience on errors
- **AFFECTS ERROR RECOVERY**

**Current Impact**: 🟢 **MEDIUM - Edge case handling**

**Implementation Section**: Section 5

- Wrap generator in try-catch
- Always send final chunk + `[DONE]` even on error
- Log exceptions properly

---

#### Gap 3.3.4: Context Handling Inconsistency

**What VSCode Expects**:

- Consistent context extraction from system and user messages
- Context preserved across conversation turns

**What Our Service Currently Does**:

- Extracts context from both system and user messages
- If context in both, only system version used
- May lose context updates in user messages
- Logic in `wormhole-oai.py` lines 252-299

**Why This Matters**:

- Context updates in conversation may be lost
- Workspace changes not reflected
- Agent may have stale information
- **AFFECTS CONTEXT AWARENESS**

**Current Impact**: 🟢 **MEDIUM - Context staleness**

**Implementation Section**: Section 4

- Merge contexts if found in multiple places
- Priority: user context > system context (more recent)
- Or concatenate both contexts

---

#### Gap 3.3.5: Template Selection Logic Complexity

**What VSCode Expects**:

- Clear template selection based on conversation state

**What Our Service Currently Does** (`template_composer.py` line 58):

- Uses `is_first` flag for template selection
- "First" definition unclear in multi-turn context
- May use wrong template for continuation

**Why This Matters**:

- Wrong template means wrong prompt structure
- Affects agent performance
- Maintenance difficulty
- **AFFECTS PROMPT QUALITY**

**Current Impact**: 🟢 **MEDIUM - Template selection clarity**

**Implementation Section**: Section 4

- Clarify template selection rules
- Document when each template should be used
- Simplify conditional logic

---

### 3.4 Low Priority Gaps (Nice-to-Have Improvements)

These are minor improvements that enhance the system but aren't necessary for core functionality.

#### Gap 3.4.1: Token Usage Calculation Inaccurate

**What VSCode Expects**:

- Accurate token counts for usage tracking
- Helps users understand API costs

**What Our Service Currently Does** (`wormhole-oai.py` lines 414-415):

- Simple word count approximation
- `len(prompt.split()) + len(response.split())`
- Not real token counting

**Why This Matters**:

- Inaccurate usage reporting
- Doesn't affect functionality
- Users can't accurately track costs
- **COSMETIC ISSUE**

**Current Impact**: 🔵 **LOW - Reporting only**

**Implementation Section**: Not critical - could add tiktoken library later

---

#### Gap 3.4.2: Max Steps Tracking Not Implemented

**What VSCode Expects**:

- Some limit on agent loop iterations
- Prevents infinite loops

**What Our Service Currently Does** (`agent_workflow.py` lines 148-153):

- `step()` function defined but never called
- No actual step limiting
- Agent could theoretically loop forever

**Why This Matters**:

- Safety mechanism for runaway loops
- Prevents resource exhaustion
- Good practice but not critical
- **SAFETY FEATURE**

**Current Impact**: 🔵 **LOW - Safety improvement**

**Implementation Section**: Could add to Section 6

- Call `step()` in agent loop
- Check `is_max_steps_reached()`
- Return error message if limit hit

---

#### Gap 3.4.3: Rules File Loading Not Validated

**What VSCode Expects**:

- Robust file loading with error handling

**What Our Service Currently Does** (`agent_workflow.py` line 139):

- Loads `templates/rules.mdx` without checking existence
- Has fallback to empty string if missing
- No explicit validation

**Why This Matters**:

- Already has fallback mechanism
- Works correctly even if file missing
- Could add explicit check for clarity
- **ALREADY HANDLED**

**Current Impact**: 🔵 **LOW - Already has fallback**

**Implementation Section**: Optional improvement - not critical

---

#### Gap 3.4.4: Conversation ID Storage Not Persistent

**What VSCode Expects**:

- Conversation state maintained across requests

**What Our Service Currently Does**:

- Global variable `active_conversation_id`
- Lost on server restart
- Not thread-safe for concurrent users

**Why This Matters**:

- Works for single-user development scenario
- Would need improvement for production multi-user
- Not a problem for current use case
- **ARCHITECTURE LIMITATION**

**Current Impact**: 🔵 **LOW - Works for current use case**

**Implementation Section**: Future enhancement

- Could use session middleware
- Could use Redis for persistence
- Not needed for single developer usage

---

### 3.5 Non-Gaps (Things That Already Work)

#### ✅ Authentication & API Key Validation

- Location: Middleware in `wormhole-oai.py`
- Status: Works correctly
- No changes needed

#### ✅ Model Listing Endpoint

- Location: `/v1/models` handler
- Status: Returns proper model list
- No changes needed

#### ✅ Message Role Parsing

- Location: Lines 252-299 in `wormhole-oai.py`
- Status: Successfully extracts messages by role
- No changes needed

#### ✅ Conversation State Detection

- Location: Lines 301-309 in `wormhole-oai.py`
- Status: Correctly detects new vs continuing conversations
- No changes needed

#### ✅ Context Tag Extraction

- Location: `prompt_utils.py` functions
- Status: Properly extracts `<context>` and `<attachments>` tags
- No changes needed

#### ✅ Final Answer Detection

- Location: `extract_final_answer()` and `has_final_answer_marker()`
- Status: Reliably identifies when agent is done
- No changes needed

#### ⚠️ Text Content Streaming

- Location: Lines 385-397 in `wormhole-oai.py`
- Status: Character-by-character streaming works for text-only responses
- **Limitation**: Does NOT work when combined with tool calls - see Gap 3.2.3

#### ✅ SSE Basic Format

- Location: Role delta, completion delta, stream terminator
- Status: All correct
- No changes needed

#### ✅ Template System

- Location: `template_composer.py` and YAML files
- Status: Jinja2 rendering works reliably
- No changes needed

#### ✅ Conversation Logging

- Location: Data folder logging callbacks
- Status: Captures all exchanges for debugging
- No changes needed

---

### 3.6 Gap Summary Matrix

| Gap ID | Priority         | Impact                                                          | Addressed In Section |
| ------ | ---------------- | --------------------------------------------------------------- | -------------------- |
| 3.1.1  | ✅ Already Fixed | System prompts injected via templates - working                 | Section 4            |
| 3.1.2  | 🔴 Critical      | Tool call streaming format wrong - tool calling broken          | Section 5            |
| 3.1.3  | 🔴 Critical      | Multi-tool NOT supported - only first parsed, needs to be built | Section 5            |
| 3.2.1  | 🟡 High          | Order-based tool result matching - unreliable                   | Section 6            |
| 3.2.2  | 🟡 High          | No status indicators in results - reduced agent quality         | Section 6            |
| 3.2.3  | 🟡 High          | Text before tool calls NOT supported - reduced UX               | Section 5            |
| 3.2.4  | 🟡 High          | SSE structure mostly correct - only tool part broken            | Section 5            |
| 3.3.1  | 🟢 Medium        | Tool call ID format cosmetic difference                         | Section 5            |
| 3.3.2  | 🟢 Medium        | No ID validation - already works                                | Section 5            |
| 3.3.3  | 🟢 Medium        | No error handling in SSE generator                              | Section 5            |
| 3.3.4  | 🟢 Medium        | Context handling inconsistency                                  | Section 4            |
| 3.3.5  | 🟢 Medium        | Template selection logic unclear                                | Section 4            |
| 3.4.1  | 🔵 Low           | Token usage inaccurate - cosmetic                               | Future               |
| 3.4.2  | 🔵 Low           | Max steps not enforced - safety                                 | Future               |
| 3.4.3  | 🔵 Low           | Rules file loading - already handled                            | N/A                  |
| 3.4.4  | 🔵 Low           | Conversation ID not persistent - works for use case             | Future               |

---

### 3.7 Implementation Priority Order

Based on the gap analysis, the recommended implementation order:

**Phase 1: Critical Fixes (Required for Basic Functionality)**

1. ✅ System Prompt Injection (Gap 3.1.1) - **ALREADY IMPLEMENTED** - Section 4 documents current approach
2. ✅ Tool Call Streaming Format (Gap 3.1.2) - Section 5
3. ✅ Multiple Tool Call Parsing (Gap 3.1.3) - Section 5

**Phase 2: High Priority Fixes (Required for Reliability)** 4. ✅ ID-Based Tool Result Correlation (Gap 3.2.1) - Section 6 5. ✅ Tool Result Status Indicators (Gap 3.2.2) - Section 6 6. ❌ Text Before Tool Calls Support (Gap 3.2.3) - Section 5 7. ✅ SSE Error Handling (Gap 3.3.3) - Section 5

**Phase 3: Quality Improvements (Recommended)** 8. Context Handling Improvements (Gap 3.3.4) - Section 4 9. Template Selection Clarity (Gap 3.3.5) - Section 4 10. Tool Call ID Format (Gap 3.3.1) - Section 5

**Phase 4: Future Enhancements (Optional)** 11. Token Usage Accuracy (Gap 3.4.1) 12. Max Steps Enforcement (Gap 3.4.2) 13. Conversation Persistence (Gap 3.4.4)

---

### 3.8 Success Criteria

After addressing all Critical and High Priority gaps, the system should achieve:

**Functional Success**:

- ✅ VSCode Copilot Chat connects successfully to OAI service
- ✅ Agent receives and processes system instructions
- ✅ Tool calls are detected and parsed correctly
- ✅ Multiple tools can be called in single response
- ✅ Tool results are matched to calls reliably
- ✅ Agent can iterate through multi-step tasks
- ✅ Final answers are detected and presented

**Quality Success**:

- ✅ SSE streaming works smoothly without errors
- ✅ Tool call format matches OpenAI specification
- ✅ Error handling prevents broken streams
- ✅ Agent has proper context and workspace awareness
- ✅ Tool execution status clearly indicated

**User Experience Success**:

- ✅ Real-time streaming feedback in VSCode
- ✅ Tool invocations shown in UI
- ⚠️ Agent explains what it's doing (limited - no text with tool calls, see Gap 3.2.3)
- ✅ Complex multi-file tasks complete successfully
- ✅ Error messages are clear and actionable

---

## 4. Prompt Injection Strategy {#prompt-injection}

## 4. Prompt Injection Strategy {#prompt-injection}

### 4.1 Current Implementation

**Discovery**: The Outlier platform **completely ignores** the `systemMessage` parameter sent in API requests. This is confirmed by:

1. Current implementation sends system message (line 58 in `agent_workflow.py`)
2. VSCode builds elaborate system prompts with instructions, tools, context
3. Agent behavior shows no awareness of these instructions unless they're in the user prompt

**Impact**: Without system prompts, the agent would receive:

- ❌ No identity/role definition ("You are Copilot...")
- ❌ No tool calling instructions (XML format, invoke syntax)
- ❌ No safety guardrails and content policies
- ❌ No workspace context (files, git status)
- ❌ No custom instructions from VSCode
- ❌ No tool definitions and parameter schemas

**Solution**: The current implementation ALREADY injects ALL system content into the user message via the template system. Additionally, we send a smaller redundant system message in case Outlier fixes their issue in the future, or for additional research. The injection approach:

1. Doesn't break VSCode's prompt parsing (no conflicts with existing tags)
2. Maintains natural conversation flow for the LLM
3. Preserves attachments, context, and tool references
4. Only happens on appropriate messages (not every turn)

### 4.2 Current Injection Approach

#### 4.2.1 When Injection Occurs

**The current implementation** injects system content ONLY when:

1. **New conversation** (no assistant messages in history) AND
2. **First user message** AND
3. **System messages exist** in the request

**Detection Logic** (already exists in `wormhole-oai.py` lines 301-309):

```python
has_assistant_messages = any(msg.get("role") == "assistant" for msg in messages)
is_new_conversation = not has_assistant_messages

if is_new_conversation:
    active_conversation_id = None  # Reset conversation
    # This is where we inject
```

**Do NOT inject on**:

- Tool result messages (already handled by `handle_tool_response`)
- Continuation messages in existing conversation
- Messages without system content

#### 4.2.2 How System Content is Currently Injected

**Current Implementation**: The template system (`template_composer.py`) automatically includes all system content at the top of prompts sent to Outlier. The structure is:

```
<system_context>
{All system message content combined}
</system_context>

{Original user message content including <context>, <attachments>, <userRequest> tags}
```

**Rationale**:

- **Top placement**: System instructions are seen first by LLM (prime context)
- **Clear separator**: `<system_context>` tag makes boundary explicit
- **Preserves existing tags**: VSCode's tags (`<context>`, `<attachments>`, etc.) remain untouched
- **Natural flow**: System context → specific request is logical for LLMs

#### 4.2.3 Format Design

**Multiple System Messages Handling**:

VSCode sends multiple system messages:

1. **Main system prompt**: Identity, instructions, mode
2. **Context prompt**: Workspace info, git status, files

**Combination Strategy**:

```
<system_context>
=== Agent Instructions ===
{First system message - identity and core instructions}

=== Workspace Context ===
{Second system message - workspace details}

{Additional system messages if any, each with clear separator}
</system_context>
```

**Example Before Injection**:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are Copilot, an AI coding assistant. You help developers write, understand, and improve code.\n\nFollow Microsoft content policies...\n\nUse tools by invoking: <invoke name=\"tool_name\">...</invoke>"
    },
    {
      "role": "system",
      "content": "Workspace: /home/user/project\nOpen files: src/main.ts, package.json\nGit branch: main (modified: 2 files)"
    },
    {
      "role": "user",
      "content": "<context>\n  <vscode.d.ts symbols definitions>\n</context>\n<attachments>\n  README.md\n</attachments>\n<userRequest>\nAdd multiply function to test.js\n</userRequest>"
    }
  ]
}
```

**Example After Injection**:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "<system_context>\n=== Agent Instructions ===\nYou are Copilot, an AI coding assistant. You help developers write, understand, and improve code.\n\nFollow Microsoft content policies...\n\nUse tools by invoking: <invoke name=\"tool_name\">...</invoke>\n\n=== Workspace Context ===\nWorkspace: /home/user/project\nOpen files: src/main.ts, package.json\nGit branch: main (modified: 2 files)\n</system_context>\n\n<context>\n  <vscode.d.ts symbols definitions>\n</context>\n<attachments>\n  README.md\n</attachments>\n<userRequest>\nAdd multiply function to test.js\n</userRequest>"
    }
  ]
}
```

**Key Points**:

- System messages are REMOVED from messages array
- All system content is prepended to FIRST user message
- Section separators (`=== Agent Instructions ===`) improve readability
- Original user message structure is preserved
- Tags are XML-style to match existing pattern

### 4.3 Implementation Details

#### 4.3.1 How It Currently Works

**Implementation**: The injection is handled by the template system in `template_composer.py`, specifically in the `initialize_system_prompt()` and related composition functions.

**Process**: System content is included in prompts sent to Outlier through the template rendering, while a smaller redundant system message is also sent (though ignored by Outlier).

#### 4.3.2 Template-Based Injection (Current Approach)

The current implementation uses the template system rather than direct message manipulation. The templates (in `agent_prompts.yaml`) already include:

```python
# This is conceptual - actual implementation uses templates
def compose_prompt_with_system_content(system_messages, user_content, tools, context):
    """
    Compose prompt with all system content included via templates.

    Args:
        messages: List of message dicts with 'role' and 'content'

    Returns:
        Modified messages list with system content injected into first user message
    """
    # Step 1: Detect if injection needed
    has_assistant = any(msg.get("role") == "assistant" for msg in messages)
    if has_assistant:
        return messages  # Don't inject on continuing conversations

    # Step 2: Collect all system messages
    system_messages = [msg for msg in messages if msg.get("role") == "system"]
    if not system_messages:
        return messages  # No system messages to inject

    # Step 3: Find first user message
    user_messages = [msg for msg in messages if msg.get("role") == "user"]
    if not user_messages:
        return messages  # No user message to inject into

    first_user_msg = user_messages[0]

    # Step 4: Build system context block
    system_context_parts = ["<system_context>"]

    for i, sys_msg in enumerate(system_messages):
        if i == 0:
            system_context_parts.append("=== Agent Instructions ===")
        else:
            system_context_parts.append(f"=== System Context {i} ===")

        system_context_parts.append(sys_msg.get("content", ""))
        system_context_parts.append("")  # Empty line separator

    system_context_parts.append("</system_context>")
    system_context_parts.append("")  # Empty line before user content

    system_context_block = "\n".join(system_context_parts)

    # Step 5: Prepend system context to user message
    original_user_content = first_user_msg.get("content", "")

    # Handle both string and list content types
    if isinstance(original_user_content, str):
        new_user_content = system_context_block + original_user_content
    elif isinstance(original_user_content, list):
        # List format (multi-part content)
        # Insert system context as first text part
        new_user_content = [
            {"type": "text", "text": system_context_block}
        ] + original_user_content
    else:
        new_user_content = system_context_block + str(original_user_content)

    # Step 6: Build new messages array
    # Remove system messages, update first user message
    new_messages = []
    user_msg_updated = False

    for msg in messages:
        if msg.get("role") == "system":
            continue  # Skip system messages
        elif msg.get("role") == "user" and not user_msg_updated:
            # Update first user message
            new_messages.append({
                "role": "user",
                "content": new_user_content
            })
            user_msg_updated = True
        else:
            new_messages.append(msg)

    return new_messages
```

#### 4.3.3 Integration Point (Currently Implemented)

**In `agent_workflow.py`**, the system content is extracted and passed to the template composer:

```python
# This is already implemented
def handle_initial_tool_request(model, messages, raw_system, tools):
    # Extract system content
    custom_instructions = extract_client_instructions(raw_system)
    context = extract_context_tag(raw_system)

    # Template composer includes system content in the prompt
    system_message = composer.initialize_system_prompt(
        tools, attachments, context, custom_instructions, user_request, is_first=True
    )
    # System content is now in the prompt sent to Outlier

    stream = body.get("stream", False)
    tools = body.get("tools", [])

    # Rest of the function continues with modified messages array
    # The existing parsing logic will now extract system context from user message
```

#### 4.3.4 Compatibility with Existing Parsing

**Current Parsing Logic** (lines 252-299):

```python
for i, msg in enumerate(messages):
    role = msg.get("role")
    content = msg.get("content", "")

    if role == "system":
        raw_system = content
        # ... extract context from system
    elif role == "user":
        raw_user = content
        # ... extract context, attachments, userRequest from user
```

**After Injection**:

- No more `role == "system"` messages (they're removed)
- All system content is now in `role == "user"` message
- Existing tag extraction (`<context>`, `<attachments>`, `<userRequest>`) continues to work
- `raw_system` becomes empty (which is fine, it wasn't used effectively anyway)

**BUT** we need to **extract system context for logging**:

```python
# Modified parsing to extract injected system context
for i, msg in enumerate(messages):
    role = msg.get("role")
    content = msg.get("content", "")

    if role == "user":
        raw_user = content

        # NEW: Extract injected system context
        system_context_match = re.search(
            r"<system_context>(.*?)</system_context>",
            raw_user,
            re.DOTALL
        )
        if system_context_match:
            raw_system = system_context_match.group(1)  # Capture system content

        # Existing extractions
        context_match = re.search(r"<context>(.*?)</context>", raw_user, re.DOTALL)
        if context_match:
            context = context_match.group(0)

        # ... rest of existing logic
```

### 4.4 Edge Cases and Solutions

#### 4.4.1 Edge Case: No System Messages

**Scenario**: Client sends only user message (unlikely with VSCode, but possible)

**Solution**:

```python
system_messages = [msg for msg in messages if msg.get("role") == "system"]
if not system_messages:
    return messages  # No injection needed, return as-is
```

**Impact**: None, function returns early

#### 4.4.2 Edge Case: Multiple System Messages

**Scenario**: VSCode sends 3+ system messages (identity, context, experiment flags)

**Solution**: Inject ALL with numbered separators:

```
<system_context>
=== Agent Instructions ===
{First system message}

=== System Context 2 ===
{Second system message}

=== System Context 3 ===
{Third system message}
</system_context>
```

**Impact**: LLM sees all system information in order

#### 4.4.3 Edge Case: Very Long System Message

**Scenario**: System message is 5000+ characters (with full tool descriptions)

**Solution**:

- **Accept the length**: Modern LLMs handle long contexts
- **Log warning** if exceeds threshold:
  ```python
  if len(system_context_block) > 10000:
      print(f"[Warning] Large system context: {len(system_context_block)} chars")
  ```
- **Future optimization**: Could compress tool definitions to simple format

**Impact**: May consume more tokens, but necessary for agent functionality

#### 4.4.4 Edge Case: Conversation History with Tool Results

**Scenario**: Message array contains: system, user, assistant, tool, user

**Solution**: Injection only happens if **NO assistant messages**:

```python
has_assistant = any(msg.get("role") == "assistant" for msg in messages)
if has_assistant:
    return messages  # Don't inject, this is conversation continuation
```

**Impact**: Tool result messages are NOT injected (handled separately by `handle_tool_response`)

#### 4.4.5 Edge Case: User Message Contains Existing `<system_context>` Tag

**Scenario**: User manually types `<system_context>` in their message (extremely unlikely)

**Solution**:

- **Detection**: Check for existing tag before injection
- **Handling**: If found, use different tag name `<agent_system_context>`

```python
if "<system_context>" in original_user_content:
    # User has this tag in their message, use alternative
    opening_tag = "<agent_system_context>"
    closing_tag = "</agent_system_context>"
else:
    opening_tag = "<system_context>"
    closing_tag = "</system_context>"
```

**Impact**: Minimal - avoids tag collision

#### 4.4.6 Edge Case: Multi-Part User Content (List Format)

**Scenario**: User content is a list of parts (text + images):

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "Check this image"},
    {"type": "image", "source": {...}}
  ]
}
```

**Solution**: Insert system context as **first text part**:

```python
if isinstance(original_user_content, list):
    new_user_content = [
        {"type": "text", "text": system_context_block}
    ] + original_user_content
```

**Impact**: Preserves all content parts, system context comes first

### 4.5 Validation Strategy

#### 4.5.1 Unit Testing

**Test File**: `/services/oai/test_injection.py`

**Test Cases**:

```python
def test_inject_new_conversation():
    """System messages injected on new conversation"""
    messages = [
        {"role": "system", "content": "You are Copilot"},
        {"role": "user", "content": "Hello"}
    ]
    result = inject_system_into_user_message(messages)
    assert len(result) == 1  # Only user message remains
    assert "<system_context>" in result[0]["content"]
    assert "You are Copilot" in result[0]["content"]

def test_no_inject_continuing_conversation():
    """No injection when assistant messages present"""
    messages = [
        {"role": "system", "content": "You are Copilot"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "How are you?"}
    ]
    result = inject_system_into_user_message(messages)
    assert len([m for m in result if m["role"] == "system"]) == 1  # System msg unchanged

def test_multiple_system_messages():
    """Multiple system messages all injected"""
    messages = [
        {"role": "system", "content": "Instructions"},
        {"role": "system", "content": "Context"},
        {"role": "system", "content": "Rules"},
        {"role": "user", "content": "Task"}
    ]
    result = inject_system_into_user_message(messages)
    assert "Instructions" in result[0]["content"]
    assert "Context" in result[0]["content"]
    assert "Rules" in result[0]["content"]
    assert "=== Agent Instructions ===" in result[0]["content"]
    assert "=== System Context 2 ===" in result[0]["content"]

def test_preserve_user_tags():
    """Original user tags preserved after injection"""
    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "<context>...</context><userRequest>Task</userRequest>"}
    ]
    result = inject_system_into_user_message(messages)
    assert "<context>" in result[0]["content"]
    assert "<userRequest>" in result[0]["content"]
    assert result[0]["content"].index("<system_context>") < result[0]["content"].index("<context>")

def test_list_content_format():
    """Multi-part content handled correctly"""
    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": [
            {"type": "text", "text": "Hello"},
            {"type": "image", "source": "..."}
        ]}
    ]
    result = inject_system_into_user_message(messages)
    assert isinstance(result[0]["content"], list)
    assert result[0]["content"][0]["type"] == "text"
    assert "<system_context>" in result[0]["content"][0]["text"]
```

#### 4.5.2 Integration Testing

**Test with Actual VSCode Request**:

1. **Capture real VSCode request** from data dumps
2. **Apply injection** and verify structure
3. **Send to Outlier** and check response
4. **Verify agent behavior** shows awareness of system instructions

**Test Checklist**:

- [ ] Agent uses correct tool invoke syntax (from system instructions)
- [ ] Agent identifies itself correctly ("I'm Copilot")
- [ ] Agent respects content policies (if mentioned in system)
- [ ] Agent has workspace awareness (file paths, git branch)
- [ ] Tool definitions are understood (parameters, descriptions)

#### 4.5.3 Outlier Log Verification

**Check Outlier Logs**:

1. **Conversation creation**: First prompt should contain `<system_context>` block
2. **Prompt structure**: System instructions at top, then user content
3. **No system parameter**: Verify `systemMessage` is empty or ignored

**Log Example** (after injection):

```
[Agent] Creating new conversation
Prompt length: 3500 chars
Prompt preview:
<system_context>
=== Agent Instructions ===
You are Copilot, an AI coding assistant...

Use tools by invoking: <invoke name="tool_name">...
</system_context>

<userRequest>
Add multiply function
</userRequest>
```

#### 4.5.4 Agent Behavior Tests

**Functional Tests**:

1. **Simple request**: "Hello" → Should identify as Copilot
2. **Tool request**: "Read README.md" → Should use `<invoke name="read_file">` syntax
3. **Multi-step**: "Read file and summarize" → Should call tool, then provide final answer
4. **Context awareness**: "What files are open?" → Should reference workspace context

**Expected Behaviors**:

- ✅ Correct tool invocation syntax
- ✅ Awareness of available tools
- ✅ Follows instructions (e.g., "use XML format")
- ✅ Respects workspace context

### 4.6 Redundant System Message

**Current Approach**: In addition to injecting system content into prompts, we also send a smaller system message to Outlier (even though it's ignored). This is for:

1. **Future-proofing**: If Outlier fixes their system message handling
2. **Research purposes**: To facilitate further investigation
3. **Redundancy**: Belt-and-suspenders approach

**If Changes Needed**:

1. **Feature Flag**:

   ```python
   ENABLE_SYSTEM_INJECTION = os.getenv("ENABLE_SYSTEM_INJECTION", "true").lower() == "true"

   if ENABLE_SYSTEM_INJECTION:
       messages = inject_system_into_user_message(messages)
   ```

2. **Gradual Rollout**: Test with subset of models first
3. **Monitoring**: Log injection success/failure rates
4. **Quick Disable**: Set env var `ENABLE_SYSTEM_INJECTION=false` to revert

### 4.7 Alternative Injection Formats Considered

#### 4.7.1 Markdown Sections (Rejected)

```markdown
# System Instructions

You are Copilot...

# Workspace Context

Workspace: /home/user...

# User Request

Add multiply function...
```

**Pros**: Natural markdown structure
**Cons**:

- Conflicts with user's actual markdown
- Less explicit boundaries
- Harder to parse back out if needed

#### 4.7.2 JSON Block (Rejected)

```json
[SYSTEM_CONTEXT]
{
  "instructions": "You are Copilot...",
  "context": "Workspace: ..."
}
[/SYSTEM_CONTEXT]

User request: Add multiply function
```

**Pros**: Structured data
**Cons**:

- JSON parsing overhead
- Less natural for LLM
- Conflicts with code in user messages

#### 4.7.3 HTML Comments (Rejected)

```html
<!-- SYSTEM_INSTRUCTIONS
You are Copilot...
-->

User request: Add multiply function
```

**Pros**: Comments are often ignored in output
**Cons**:

- May be stripped by some LLMs
- Less visible to model
- Conflicts with HTML in user messages

#### 4.7.4 Selected Format: XML Tags (Chosen)

```xml
<system_context>
=== Agent Instructions ===
You are Copilot...
</system_context>

<userRequest>
Add multiply function
</userRequest>
```

**Pros**:

- ✅ Explicit boundaries with XML tags
- ✅ Matches existing VSCode tag pattern (`<context>`, `<attachments>`)
- ✅ Natural for LLMs (widely used in training data)
- ✅ Easy to parse if needed
- ✅ Section markers improve readability

**Selected**: This format balances clarity, compatibility, and LLM friendliness

### 4.8 Implementation Checklist

- [ ] Create `inject_system_into_user_message()` function in `wormhole-oai.py`
- [ ] Add injection call in `chat_completions()` before message parsing
- [ ] Update parsing logic to extract injected system context for logging
- [ ] Add feature flag for gradual rollout
- [ ] Write unit tests for injection function
- [ ] Test with real VSCode requests
- [ ] Monitor Outlier logs for injection success
- [ ] Verify agent behavior improvements
- [ ] Document injection format in README
- [ ] Update architecture diagrams

### 4.9 Current Status

**With Current Implementation**:

- ✅ Agent identifies as Copilot
- ✅ Agent uses correct XML tool syntax
- ✅ Agent references workspace context
- ✅ Agent follows safety guidelines
- ✅ Consistent, predictable behavior
- ✅ VSCode integration works

**How It Works**: The template-based injection automatically includes all system content in the prompts sent to Outlier. This ensures the agent receives instructions, tool definitions, and context even though Outlier ignores the separate system message parameter.

**Redundant System Message**: A smaller system message is also sent (though ignored) for future-proofing and research purposes.

**Success Metric**: Agent uses `<invoke name="tool_name">` syntax reliably and shows awareness of role/context in responses - **this is currently achieved**.

---

## 5. Tool Calling Response Format {#tool-calling-format}

### 5.1 The SSE Streaming Challenge

**Critical Issue**: VSCode Copilot expects **specific SSE delta formats** for tool calls that differ significantly from our current implementation.

**Current Implementation** (lines 370-383 in `wormhole-oai.py`):

```python
# WRONG: Sends complete tool call in single chunk
for tool_call in tool_calls:
    tool_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"tool_calls": [tool_call]},  # Complete object
            "finish_reason": None
        }]
    }
    yield f"data: {json.dumps(tool_chunk)}\n\n"
```

**VSCode Expectation**: Incremental streaming with proper `beginToolCalls` signal and indexed deltas.

**⚠️ ADDITIONAL LIMITATION**: The current `parse_tool_call()` function only detects and returns ONE tool call. Even if the streaming format is fixed, multiple tool calls in a single response are NOT supported.

### 5.2 Understanding VSCode's Tool Call Detection

From `vscode_copilot_workflow_final.md` Section 3:

VSCode's SSE parser (`SSEProcessor`) performs the following:

1. **Buffers Partial Tool Calls**: Accumulates `tool_calls[].function.arguments` chunks across multiple deltas
2. **Detects beginToolCalls**: Emits marker when model transitions to tool calling (after text content)
3. **Assembles Complete Tool Calls**: Combines partial JSON chunks when `finish_reason` indicates completion
4. **Emits IResponseDelta**: Normalizes to unified format with `beginToolCalls` and `copilotToolCalls`

**Key Insight**: VSCode expects **incremental argument streaming**, NOT complete tool call objects.

### 5.3 Correct SSE Event Sequences

#### 5.3.1 Sequence for Text-Only Response

**Scenario**: Model responds with plain text, no tool calls.

```
1. Role Delta (First Chunk):
data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

2. Text Content Deltas (Character by Character):
data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"H"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"e"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"l"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"l"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"o"},"finish_reason":null}]}

3. Completion Delta (Final Chunk):
data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

4. Stream Terminator:
data: [DONE]
```

**Current Status**: ✅ **Already correct** in lines 385-397 of `wormhole-oai.py`

#### 5.3.2 Sequence for Tool Call Response (Single Tool)

**Scenario**: Model calls one tool without preceding text.

```
1. Role Delta:
data: {"id":"chatcmpl-def","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

2. Tool Call Start (ID + Type + Name):
data: {"id":"chatcmpl-def","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_abc123","type":"function","function":{"name":"read_file","arguments":""}}]},"finish_reason":null}]}

3. Arguments Delta 1 (Opening Brace):
data: {"id":"chatcmpl-def","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{"}}]},"finish_reason":null}]}

4. Arguments Delta 2 (Parameter Name):
data: {"id":"chatcmpl-def","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"path\":"}}]},"finish_reason":null}]}

5. Arguments Delta 3 (Parameter Value):
data: {"id":"chatcmpl-def","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"README.md\""}}]},"finish_reason":null}]}

6. Arguments Delta 4 (Closing Brace):
data: {"id":"chatcmpl-def","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"}"}}]},"finish_reason":null}]}

7. Completion Delta (Tool Calls Finish Reason):
data: {"id":"chatcmpl-def","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}

8. Stream Terminator:
data: [DONE]
```

**Key Points**:

- **index**: Each tool call has an index (0, 1, 2, ...)
- **Incremental arguments**: Arguments are streamed in chunks, NOT complete
- **First chunk**: Contains `id`, `type`, `function.name`, and empty `arguments: ""`
- **Subsequent chunks**: Only contain `index` and `function.arguments` delta
- **finish_reason**: Must be `"tool_calls"` (NOT `"function_call"`)

**Current Status**: ❌ **WRONG** - Sends complete tool call in one chunk

#### 5.3.3 Sequence for Multiple Tool Calls

**Scenario**: Model calls two tools in one response.

```
1. Role Delta:
data: {"id":"chatcmpl-ghi","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

2. First Tool Call Start (index=0):
data: {"id":"chatcmpl-ghi","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_xyz1","type":"function","function":{"name":"edit_file","arguments":""}}]},"finish_reason":null}]}

3. First Tool Arguments (Incremental):
data: {"id":"chatcmpl-ghi","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"filePath\":\"/path/test.js\",\"code\":\"function multiply(a,b){return a*b;}\"}"}}]},"finish_reason":null}]}

4. Second Tool Call Start (index=1):
data: {"id":"chatcmpl-ghi","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"id":"call_xyz2","type":"function","function":{"name":"edit_file","arguments":""}}]},"finish_reason":null}]}

5. Second Tool Arguments (Incremental):
data: {"id":"chatcmpl-ghi","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"function":{"arguments":"{\"filePath\":\"/path/server.js\",\"code\":\"const jokes = ['Why did the chicken cross the road?'];}\"}"}}]},"finish_reason":null}]}

6. Completion Delta:
data: {"id":"chatcmpl-ghi","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}

7. Stream Terminator:
data: [DONE]
```

**Key Points**:

- Each tool call gets a unique `index` (0, 1, 2, ...)
- Tool calls are streamed **sequentially** (finish first, then start second)
- Both finish with single `finish_reason: "tool_calls"` at the end

#### 5.3.4 Sequence for Mixed Response (Text + Tool Calls)

**Scenario**: Model provides explanation, then calls tools.

**⚠️ IMPORTANT**: This is the EXPECTED format from VSCode, but **our current OAI service does NOT support this**. When tool calls are present, no text content is emitted. See Gap 3.2.3.

```
1. Role Delta:
data: {"id":"chatcmpl-jkl","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

2. Text Content First:
data: {"id":"chatcmpl-jkl","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"I'll make two changes:\n1. Add multiply to test.js\n2. Add jokes to server.js"},"finish_reason":null}]}

3. Tool Call Start (After Text):
data: {"id":"chatcmpl-jkl","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_mixed1","type":"function","function":{"name":"edit_file","arguments":""}}]},"finish_reason":null}]}

4. Tool Arguments:
data: {"id":"chatcmpl-jkl","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"filePath\":\"test.js\",\"code\":\"function multiply(a,b){return a*b;}\"}"}}]},"finish_reason":null}]}

5. Second Tool Call:
data: {"id":"chatcmpl-jkl","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"id":"call_mixed2","type":"function","function":{"name":"edit_file","arguments":""}}]},"finish_reason":null}]}

6. Second Tool Arguments:
data: {"id":"chatcmpl-jkl","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"function":{"arguments":"{\"filePath\":\"server.js\",\"code\":\"const jokes = [...];}\"}"}}]},"finish_reason":null}]}

7. Completion:
data: {"id":"chatcmpl-jkl","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}

8. Terminator:
data: [DONE]
```

**Critical**: VSCode detects transition from text to tool calls and emits `beginToolCalls` internally. We don't need to send this explicitly - it's derived by the parser.

**Current Limitation**: Our service currently does not emit text when tool calls are present. This needs to be implemented to match the expected behavior.

### 5.4 Delta Structure Specifications

#### 5.4.1 Role Delta (First Chunk)

```python
{
    "id": "chatcmpl-{uuid}",
    "object": "chat.completion.chunk",
    "created": int(time.time()),
    "model": model_name,
    "system_fingerprint": None,
    "choices": [{
        "index": 0,
        "delta": {"role": "assistant"},
        "logprobs": None,
        "finish_reason": None
    }]
}
```

**When**: First chunk of every response
**Purpose**: Establishes assistant role

#### 5.4.2 Text Content Delta

```python
{
    "id": "chatcmpl-{uuid}",
    "object": "chat.completion.chunk",
    "created": timestamp,
    "model": model_name,
    "system_fingerprint": None,
    "choices": [{
        "index": 0,
        "delta": {"content": "single_char_or_word"},
        "logprobs": None,
        "finish_reason": None
    }]
}
```

**When**: For each character/word of text response
**Granularity**: Can be character-by-character OR word-by-word (VSCode handles both)

#### 5.4.3 Tool Call Start Delta

```python
{
    "id": "chatcmpl-{uuid}",
    "object": "chat.completion.chunk",
    "created": timestamp,
    "model": model_name,
    "system_fingerprint": None,
    "choices": [{
        "index": 0,
        "delta": {
            "tool_calls": [{
                "index": tool_index,           # 0, 1, 2, ...
                "id": "call_{24_hex_chars}",   # Unique ID
                "type": "function",
                "function": {
                    "name": "tool_name",
                    "arguments": ""            # Empty string initially
                }
            }]
        },
        "logprobs": None,
        "finish_reason": None
    }]
}
```

**When**: First chunk for each tool call
**Required Fields**: `index`, `id`, `type`, `function.name`, `function.arguments`
**Note**: `arguments` MUST be empty string `""` in first chunk

#### 5.4.4 Tool Call Arguments Delta

```python
{
    "id": "chatcmpl-{uuid}",
    "object": "chat.completion.chunk",
    "created": timestamp,
    "model": model_name,
    "system_fingerprint": None,
    "choices": [{
        "index": 0,
        "delta": {
            "tool_calls": [{
                "index": tool_index,      # Same index as start delta
                "function": {
                    "arguments": "partial_json_string"
                }
            }]
        },
        "logprobs": None,
        "finish_reason": None
    }]
}
```

**When**: For each chunk of JSON arguments
**Required Fields**: `index`, `function.arguments`
**Optional Fields**: Can omit `id`, `type`, `function.name` (already sent)
**Chunking**: Can send entire JSON in one delta OR split across multiple

#### 5.4.5 Completion Delta

```python
{
    "id": "chatcmpl-{uuid}",
    "object": "chat.completion.chunk",
    "created": timestamp,
    "model": model_name,
    "system_fingerprint": None,
    "choices": [{
        "index": 0,
        "delta": {},                    # Empty delta
        "logprobs": None,
        "finish_reason": "stop" | "tool_calls" | "length"
    }]
}
```

**When**: Final chunk before `[DONE]`
**finish_reason Values**:

- `"stop"`: Normal completion (text response)
- `"tool_calls"`: Completed with tool calls
- `"length"`: Hit token limit
- `"content_filter"`: Content policy violation (rare)

#### 5.4.6 Stream Terminator

```
data: [DONE]

```

**Format**: Literal string `"data: [DONE]\n\n"`
**When**: After final completion delta
**Required**: VSCode expects this to know stream is complete

### 5.5 Current Implementation Analysis

#### 5.5.1 What's Working

**File**: `wormhole-oai.py`, lines 353-404

✅ **Text Streaming** (lines 385-397):

```python
elif clean_text:
    for char in clean_text:
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": model,
            "system_fingerprint": None,
            "choices": [{
                "index": 0,
                "delta": {"content": char},
                "logprobs": None,
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(chunk)}\n\n"
```

**Status**: ✅ Correct character-by-character streaming

✅ **Role Delta** (lines 356-368):

```python
first_chunk = {
    "id": chunk_id,
    "object": "chat.completion.chunk",
    "created": created_time,
    "model": model,
    "system_fingerprint": None,
    "choices": [{
        "index": 0,
        "delta": {"role": "assistant"},
        "logprobs": None,
        "finish_reason": None
    }]
}
yield f"data: {json.dumps(first_chunk)}\n\n"
```

**Status**: ✅ Correct role establishment

✅ **Completion Delta** (lines 399-411):

```python
final_chunk = {
    "id": chunk_id,
    "object": "chat.completion.chunk",
    "created": created_time,
    "model": model,
    "system_fingerprint": None,
    "choices": [{
        "index": 0,
        "delta": {},
        "logprobs": None,
        "finish_reason": "tool_calls" if tool_calls else "stop"
    }]
}
yield f"data: {json.dumps(final_chunk)}\n\n"
```

**Status**: ✅ Correct finish_reason logic

✅ **Stream Terminator** (line 412):

```python
yield "data: [DONE]\n\n"
```

**Status**: ✅ Correct format

#### 5.5.2 What's Broken

❌ **Tool Call Streaming** (lines 370-383):

```python
if tool_calls:
    for tool_call in tool_calls:
        tool_chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": model,
            "system_fingerprint": None,
            "choices": [{
                "index": 0,
                "delta": {"tool_calls": [tool_call]},  # WRONG: Complete object
                "logprobs": None,
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(tool_chunk)}\n\n"
```

**Problems**:

1. ❌ Sends **complete tool call object** instead of incremental deltas
2. ❌ No `index` field in tool call object (required for buffering)
3. ❌ Arguments are complete JSON, not streamed
4. ❌ All fields sent in every chunk (should only send once)

**Impact**: VSCode's SSE parser may fail to correctly buffer and assemble tool calls.

### 5.6 Required Implementation Changes

#### 5.6.1 Detect Tool Calls from Outlier Response

**Location**: `agent_workflow.py`, `parse_tool_call()` function

**Current Behavior**: Returns single tool call OR None (NOT a list)

```python
def parse_tool_call(text):
    # ... parsing logic ...
    if tool_name:
        return (cleaned_text, {
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(parameters)
            }
        })  # Returns single object
    return (None, None)
```

**❌ CRITICAL LIMITATION**: Only parses ONE tool call from response. If Outlier returns multiple `<invoke>` tags, only the first is detected.

**Required Change**: BUILD NEW `parse_all_tool_calls()` function to parse ALL tool calls from response

```python
def parse_all_tool_calls(text):
    """
    **NEW FUNCTION TO BE CREATED** - Parse ALL tool calls from Outlier response.
    This does NOT exist yet and needs to be built from scratch.

    Returns:
        cleaned_text: Text with all invoke tags removed
        tool_calls: List of tool call dicts (NOT single object like current parse_tool_call)
    """
    tool_calls = []
    cleaned_text = text

    # Find all invoke patterns
    invoke_pattern = r'<invoke name="([^"]+)">(.*?)</invoke>'
    matches = re.finditer(invoke_pattern, text, re.DOTALL)

    for match in matches:
        tool_name = match.group(1)
        invoke_content = match.group(2)

        # Skip final_answer (it's not a real tool call)
        if tool_name == "final_answer":
            continue

        # Extract parameters
        parameters = {}
        param_pattern = r'<parameter name="([^"]+)">(.*?)</parameter>'
        for param_match in re.finditer(param_pattern, invoke_content, re.DOTALL):
            param_name = param_match.group(1)
            param_value = param_match.group(2).strip()
            parameters[param_name] = param_value

        # Create tool call object
        tool_call = {
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(parameters)
            }
        }
        tool_calls.append(tool_call)

        # Remove from cleaned text
        cleaned_text = cleaned_text.replace(match.group(0), "")

    return cleaned_text.strip(), tool_calls
```

**Integration**: Replace existing `parse_tool_call()` calls (which return single object) with new `parse_all_tool_calls()` (which returns list) in:

- `handle_initial_tool_request()` line 226
- `handle_tool_response()` line 223
- **NOTE**: All callers must be updated to handle list of tool calls instead of single object

#### 5.6.2 Modify SSE Generator Function

**Location**: `wormhole-oai.py`, lines 353-404

**Complete Replacement**:

```python
async def generate():
    """
    SSE stream generator with proper incremental tool call streaming.
    """
    chunk_id = completion_id

    # 1. Role Delta (First Chunk)
    first_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "system_fingerprint": None,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant"},
            "logprobs": None,
            "finish_reason": None
        }]
    }
    yield f"data: {json.dumps(first_chunk)}\n\n"

    # 2. Text Content (if exists)
    if clean_text:
        for char in clean_text:
            chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "system_fingerprint": None,
                "choices": [{
                    "index": 0,
                    "delta": {"content": char},
                    "logprobs": None,
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(chunk)}\n\n"

    # 3. Tool Calls (if exist) - PROPER INCREMENTAL STREAMING
    if tool_calls:
        for tool_index, tool_call in enumerate(tool_calls):
            # Extract tool call components
            tool_id = tool_call["id"]
            tool_name = tool_call["function"]["name"]
            tool_args = tool_call["function"]["arguments"]  # JSON string

            # 3a. Tool Call Start Delta
            start_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "system_fingerprint": None,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": tool_index,
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": ""  # Empty initially
                            }
                        }]
                    },
                    "logprobs": None,
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(start_chunk)}\n\n"

            # 3b. Tool Arguments Deltas (Stream Arguments Incrementally)
            # Option 1: Stream entire JSON in one chunk (simplest)
            args_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "system_fingerprint": None,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": tool_index,
                            "function": {
                                "arguments": tool_args  # Complete JSON string
                            }
                        }]
                    },
                    "logprobs": None,
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(args_chunk)}\n\n"

            # Option 2: Stream arguments character-by-character (more realistic)
            # Uncomment below to enable character-by-character argument streaming
            # for char in tool_args:
            #     args_chunk = {
            #         "id": chunk_id,
            #         "object": "chat.completion.chunk",
            #         "created": created_time,
            #         "model": model,
            #         "system_fingerprint": None,
            #         "choices": [{
            #             "index": 0,
            #             "delta": {
            #                 "tool_calls": [{
            #                     "index": tool_index,
            #                     "function": {"arguments": char}
            #                 }]
            #             },
            #             "logprobs": None,
            #             "finish_reason": None
            #         }]
            #     }
            #     yield f"data: {json.dumps(args_chunk)}\n\n"

    # 4. Completion Delta (Final Chunk)
    final_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "system_fingerprint": None,
        "choices": [{
            "index": 0,
            "delta": {},
            "logprobs": None,
            "finish_reason": "tool_calls" if tool_calls else "stop"
        }]
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"

    # 5. Stream Terminator
    yield "data: [DONE]\n\n"
```

**Key Changes**:

1. ✅ Added `tool_index` to track tool call position
2. ✅ Split tool call into **start delta** (id, type, name) and **args delta**
3. ✅ Set `arguments: ""` in start delta (required by spec)
4. ✅ Stream arguments separately with only `index` and `function.arguments`
5. ✅ Provide two options: single-chunk args OR character-by-character

#### 5.6.3 Argument Streaming Strategy

**Trade-off**: Streaming granularity vs simplicity

**Option A: Single Chunk Arguments** (Recommended):

```python
args_chunk = {
    "delta": {
        "tool_calls": [{
            "index": tool_index,
            "function": {"arguments": tool_args}  # Complete JSON
        }]
    }
}
```

**Pros**:

- ✅ Simpler implementation
- ✅ Fewer SSE events
- ✅ Faster overall streaming
- ✅ Still compliant with OpenAI spec

**Cons**:

- ⚠️ Less realistic streaming experience
- ⚠️ Arguments appear instantly

**Option B: Character-by-Character** (More Realistic):

```python
for char in tool_args:
    args_chunk = {
        "delta": {
            "tool_calls": [{
                "index": tool_index,
                "function": {"arguments": char}
            }]
        }
    }
```

**Pros**:

- ✅ Matches real LLM streaming behavior
- ✅ Better UX (progressive display)
- ✅ More authentic OpenAI emulation

**Cons**:

- ⚠️ More SSE events (could be 100+ per tool call)
- ⚠️ Slightly slower streaming
- ⚠️ More complex to implement

**Recommendation**: Start with **Option A** (single chunk), add **Option B** later if needed for realism.

### 5.7 Complete Working Examples

#### 5.7.1 Example 1: Text-Only Response

**Outlier Response**:

```
I'll help you with that task. The multiply function is a simple mathematical operation.
```

**Generated SSE Stream**:

```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"I"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"'"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"l"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"l"},"finish_reason":null}]}

[... continuing for each character ...]

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

**VSCode Parsing Result**:

```python
IResponseDelta {
    "text": "I'll help you with that task. The multiply function is a simple mathematical operation.",
    "copilotToolCalls": None,
    "beginToolCalls": None
}
```

#### 5.7.2 Example 2: Single Tool Call

**⚠️ IMPORTANT**: This example shows text preceding a tool call, which is the EXPECTED behavior but **NOT currently supported** by our OAI service (see Gap 3.2.3). Currently, when tool calls are present, no text content is emitted. The "Generated SSE Stream" below shows the desired format once this limitation is fixed.

**Outlier Response**:

```
I'll read the README file for you.
<invoke name="read_file">
<parameter name="path">README.md</parameter>
</invoke>
```

**Parsed**:

- `clean_text`: `"I'll read the README file for you."`
- `tool_calls`:
  ```python
  [{
      "id": "call_a1b2c3d4e5f6g7h8i9j0k1l2",
      "type": "function",
      "function": {
          "name": "read_file",
          "arguments": '{"path":"README.md"}'
      }
  }]
  ```

**Generated SSE Stream**:

```
data: {"id":"chatcmpl-def456","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-def456","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"I'll read the README file for you."},"finish_reason":null}]}

data: {"id":"chatcmpl-def456","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_a1b2c3d4e5f6g7h8i9j0k1l2","type":"function","function":{"name":"read_file","arguments":""}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-def456","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"path\":\"README.md\"}"}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-def456","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}

data: [DONE]
```

**VSCode Parsing Result**:

```python
# Delta 1: Text content
IResponseDelta {
    "text": "I'll read the README file for you.",
    "copilotToolCalls": None,
    "beginToolCalls": None
}

# Delta 2: Begin tool calls (automatically detected by parser)
IResponseDelta {
    "text": "",
    "beginToolCalls": [{"name": "read_file"}],
    "copilotToolCalls": None
}

# Delta 3: Complete tool call (after buffering)
IResponseDelta {
    "text": "",
    "beginToolCalls": None,
    "copilotToolCalls": [{
        "id": "call_a1b2c3d4e5f6g7h8i9j0k1l2",
        "name": "read_file",
        "arguments": '{"path":"README.md"}'
    }]
}
```

#### 5.7.3 Example 3: Multiple Tool Calls

**⚠️ IMPORTANT**: This example shows text preceding tool calls, which is the EXPECTED behavior but **NOT currently supported** by our OAI service (see Gap 3.2.3). Currently, when tool calls are present, no text content is emitted.

**Outlier Response**:

```
I'll make two changes:
1. Add multiply function to test.js
2. Add jokes to server.js

<invoke name="edit_file">
<parameter name="filePath">/home/user/project/test.js</parameter>
<parameter name="code">function multiply(a, b) { return a * b; }</parameter>
</invoke>

<invoke name="edit_file">
<parameter name="filePath">/home/user/project/server.js</parameter>
<parameter name="code">const jokes = ['Why did the chicken cross the road?', 'To get to the other side!'];</parameter>
</invoke>
```

**Parsed**:

- `clean_text`: `"I'll make two changes:\n1. Add multiply function to test.js\n2. Add jokes to server.js"`
- `tool_calls`:
  ```python
  [
      {
          "id": "call_tool1_xyz123abc456def789",
          "type": "function",
          "function": {
              "name": "edit_file",
              "arguments": '{"filePath":"/home/user/project/test.js","code":"function multiply(a, b) { return a * b; }"}'
          }
      },
      {
          "id": "call_tool2_xyz456abc789def012",
          "type": "function",
          "function": {
              "name": "edit_file",
              "arguments": '{"filePath":"/home/user/project/server.js","code":"const jokes = [\'Why did the chicken cross the road?\', \'To get to the other side!\'];"}'
          }
      }
  ]
  ```

**Generated SSE Stream**:

```
data: {"id":"chatcmpl-ghi789","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-ghi789","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"I'll make two changes:\n1. Add multiply function to test.js\n2. Add jokes to server.js"},"finish_reason":null}]}

data: {"id":"chatcmpl-ghi789","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_tool1_xyz123abc456def789","type":"function","function":{"name":"edit_file","arguments":""}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-ghi789","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"filePath\":\"/home/user/project/test.js\",\"code\":\"function multiply(a, b) { return a * b; }\"}"}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-ghi789","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"id":"call_tool2_xyz456abc789def012","type":"function","function":{"name":"edit_file","arguments":""}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-ghi789","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"function":{"arguments":"{\"filePath\":\"/home/user/project/server.js\",\"code\":\"const jokes = ['Why did the chicken cross the road?', 'To get to the other side!'];\"}"}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-ghi789","object":"chat.completion.chunk","created":1699876543,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}

data: [DONE]
```

**VSCode Parsing Result**:

```python
# Delta 1: Text
IResponseDelta {
    "text": "I'll make two changes:\n1. Add multiply function to test.js\n2. Add jokes to server.js",
}

# Delta 2: Begin tool calls
IResponseDelta {
    "beginToolCalls": [{"name": "edit_file"}]
}

# Delta 3: Complete tool calls
IResponseDelta {
    "copilotToolCalls": [
        {
            "id": "call_tool1_xyz123abc456def789",
            "name": "edit_file",
            "arguments": '{"filePath":"/home/user/project/test.js","code":"function multiply(a, b) { return a * b; }"}'
        },
        {
            "id": "call_tool2_xyz456abc789def012",
            "name": "edit_file",
            "arguments": '{"filePath":"/home/user/project/server.js","code":"const jokes = [\'Why did the chicken cross the road?\', \'To get to the other side!\'];"}'
        }
    ]
}
```

### 5.8 Edge Cases and Handling

#### 5.8.1 Tool Call Without Preceding Text

**Scenario**: Outlier response starts directly with `<invoke>` tag.

**Handling**:

- `clean_text` will be empty string
- Still emit role delta first
- Skip text content deltas
- Emit tool call deltas immediately
- Set `finish_reason: "tool_calls"`

**Example SSE**:

```
data: {"delta":{"role":"assistant"},...}
data: {"delta":{"tool_calls":[{"index":0,"id":"...","function":{"name":"...","arguments":""}}]},...}
data: {"delta":{"tool_calls":[{"index":0,"function":{"arguments":"..."}}]},...}
data: {"delta":{},"finish_reason":"tool_calls"}
data: [DONE]
```

#### 5.8.2 Invalid JSON in Tool Arguments

**Scenario**: Outlier returns malformed XML or parameters can't be JSON-serialized.

**Current Handling**: `json.dumps(parameters)` in `parse_all_tool_calls()`

**Issue**: If parameters contain values that can't be JSON-serialized, will raise exception.

**Solution**: Add try-catch in parsing:

```python
try:
    arguments_json = json.dumps(parameters)
except (TypeError, ValueError) as e:
    print(f"[ERROR] Failed to serialize tool arguments: {e}")
    # Fallback: serialize as string values
    parameters_safe = {k: str(v) for k, v in parameters.items()}
    arguments_json = json.dumps(parameters_safe)
```

#### 5.8.3 Very Long Tool Arguments

**Scenario**: Tool arguments are 10KB+ (large code blocks, file contents).

**Handling**:

- **Option A (Single Chunk)**: Send entire JSON in one args delta
- **Option B (Character-by-Character)**: Will emit 10,000+ SSE events

**Recommendation**: Use **Option A** for simplicity. If character streaming is needed, consider chunking by words or lines instead of characters:

```python
# Word-by-word chunking (compromise)
words = tool_args.split()
for word in words:
    args_chunk = {
        "delta": {
            "tool_calls": [{
                "index": tool_index,
                "function": {"arguments": word + " "}
            }]
        }
    }
    yield f"data: {json.dumps(args_chunk)}\n\n"
```

#### 5.8.4 Final Answer After Tool Calls

**Scenario**: Outlier returns both tool calls AND final answer in same response.

**Outlier Response**:

```
<invoke name="read_file">...</invoke>
<invoke name="final_answer">
<parameter name="answer">The file contains...</parameter>
</invoke>
```

**Handling**:

- `parse_all_tool_calls()` skips `final_answer` (see `if tool_name == "final_answer": continue`)
- Extract final answer separately using `extract_final_answer()`
- Include final answer text in `clean_text`
- **⚠️ Note**: Currently our service does NOT emit text when tool calls are present (Gap 3.2.3)
- **If/when implemented**: Emit text deltas BEFORE tool call deltas
- Set `finish_reason: "stop"` (NOT `"tool_calls"`)

**SSE Sequence**:

```
1. Role delta
2. Tool call deltas (for real tools)
3. Text deltas (final answer)
4. Completion delta with finish_reason: "stop"
```

#### 5.8.5 Empty Response from Outlier

**Scenario**: Outlier returns empty string or whitespace-only.

**Handling**:

- `clean_text` will be empty
- `tool_calls` will be empty list
- Emit role delta
- Immediately emit completion delta with `finish_reason: "stop"`
- Stream will be very short

**Example**:

```
data: {"delta":{"role":"assistant"},...}
data: {"delta":{},"finish_reason":"stop"}
data: [DONE]
```

### 5.9 Testing Strategy

#### 5.9.1 Unit Tests

**Test File**: `/services/oai/test_streaming.py`

```python
import pytest
import json
from wormhole_oai import generate  # Hypothetical import

def test_text_only_streaming():
    """Test pure text response streaming"""
    clean_text = "Hello world"
    tool_calls = []

    chunks = list(generate(clean_text, tool_calls, "model", "id", 123))

    # Assertions
    assert len(chunks) > 0
    assert "role" in json.loads(chunks[0])["choices"][0]["delta"]
    assert any("content" in json.loads(c)["choices"][0]["delta"] for c in chunks)
    assert json.loads(chunks[-2])["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1] == "data: [DONE]\n\n"

def test_single_tool_call_streaming():
    """Test single tool call with proper incremental format"""
    clean_text = ""
    tool_calls = [{
        "id": "call_abc123",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": '{"path":"README.md"}'
        }
    }]

    chunks = list(generate(clean_text, tool_calls, "model", "id", 123))

    # Find tool call start chunk
    tool_start_chunks = [c for c in chunks if "tool_calls" in json.loads(c)["choices"][0]["delta"]]
    assert len(tool_start_chunks) >= 2  # Start + arguments

    # Verify start chunk has index, id, name, empty arguments
    start_delta = json.loads(tool_start_chunks[0])["choices"][0]["delta"]
    assert start_delta["tool_calls"][0]["index"] == 0
    assert start_delta["tool_calls"][0]["id"] == "call_abc123"
    assert start_delta["tool_calls"][0]["function"]["name"] == "read_file"
    assert start_delta["tool_calls"][0]["function"]["arguments"] == ""

    # Verify arguments chunk has only index and arguments
    args_delta = json.loads(tool_start_chunks[1])["choices"][0]["delta"]
    assert args_delta["tool_calls"][0]["index"] == 0
    assert args_delta["tool_calls"][0]["function"]["arguments"] == '{"path":"README.md"}'

    # Verify finish_reason
    assert json.loads(chunks[-2])["choices"][0]["finish_reason"] == "tool_calls"

def test_multiple_tool_calls_streaming():
    """Test multiple tool calls with correct indexing"""
    tool_calls = [
        {"id": "call_1", "type": "function", "function": {"name": "tool1", "arguments": '{"a":1}'}},
        {"id": "call_2", "type": "function", "function": {"name": "tool2", "arguments": '{"b":2}'}}
    ]

    chunks = list(generate("", tool_calls, "model", "id", 123))

    tool_chunks = [c for c in chunks if "tool_calls" in json.loads(c)["choices"][0]["delta"]]

    # Should have 4 chunks: start1, args1, start2, args2
    assert len(tool_chunks) == 4

    # Verify indices
    assert json.loads(tool_chunks[0])["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert json.loads(tool_chunks[1])["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert json.loads(tool_chunks[2])["choices"][0]["delta"]["tool_calls"][0]["index"] == 1
    assert json.loads(tool_chunks[3])["choices"][0]["delta"]["tool_calls"][0]["index"] == 1

def test_mixed_text_and_tool_calls():
    """Test text followed by tool calls"""
    clean_text = "I'll help you with that."
    tool_calls = [{
        "id": "call_xyz",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{}'}
    }]

    chunks = list(generate(clean_text, tool_calls, "model", "id", 123))

    # Find text chunks
    text_chunks = [c for c in chunks if "content" in json.loads(c)["choices"][0]["delta"]]
    assert len(text_chunks) > 0

    # Find tool chunks
    tool_chunks = [c for c in chunks if "tool_calls" in json.loads(c)["choices"][0]["delta"]]
    assert len(tool_chunks) >= 2

    # Verify text comes before tools (chunk order)
    text_indices = [chunks.index(tc) for tc in text_chunks]
    tool_indices = [chunks.index(tc) for tc in tool_chunks]
    assert max(text_indices) < min(tool_indices)
```

#### 5.9.2 Integration Tests

**Test with Real VSCode Client**:

1. **Setup**: Point VSCode to OAI service endpoint
2. **Test 1**: Send simple query → Verify text streaming works
3. **Test 2**: Send tool request → Verify tool calls are detected
4. **Test 3**: Check VSCode UI → Confirm tool invocation happens
5. **Test 4**: Verify tool results → Check next iteration works

**Validation Checklist**:

- [ ] VSCode shows streaming text character-by-character
- [ ] Tool calls appear in UI with correct tool names
- [ ] Tool invocation happens automatically
- [ ] Tool results are injected into next request
- [ ] Agent can iterate with multiple tool rounds
- [ ] No errors in VSCode Output panel

#### 5.9.3 Manual Testing with curl

**Test Text Streaming**:

```bash
curl -X POST http://localhost:11434/v1/chat/completions \
  -H "Authorization: Bearer $OAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello"}],
    "stream": true
  }' \
  --no-buffer
```

**Expected Output**:

```
data: {"id":"chatcmpl-...","choices":[{"delta":{"role":"assistant"},...}]}

data: {"id":"chatcmpl-...","choices":[{"delta":{"content":"H"},...}]}

data: {"id":"chatcmpl-...","choices":[{"delta":{"content":"e"},...}]}

[...]

data: [DONE]
```

**Test Tool Streaming**:

```bash
curl -X POST http://localhost:11434/v1/chat/completions \
  -H "Authorization: Bearer $OAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Read README.md"}],
    "tools": [{"type":"function","function":{"name":"read_file","parameters":{"type":"object","properties":{"path":{"type":"string"}}}}}],
    "stream": true
  }' \
  --no-buffer
```

**Expected Output** (should include):

```
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_...","type":"function","function":{"name":"read_file","arguments":""}}]},...}]}

data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"path\":\"README.md\"}"}}]},...}]}

data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}
```

### 5.10 Implementation Checklist

- [ ] **BUILD NEW**: Create `parse_all_tool_calls()` function in `agent_workflow.py` (does NOT exist yet)
- [ ] Replace existing `parse_tool_call()` calls with new `parse_all_tool_calls()`
- [ ] Update all callers to handle list return type instead of single object
- [ ] Update `generate()` function in `wormhole-oai.py` with proper tool streaming
- [ ] Add `tool_index` tracking in SSE generator
- [ ] Implement tool call start delta (id, type, name, empty arguments)
- [ ] Implement tool call arguments delta (index, arguments only)
- [ ] Test with single tool call
- [ ] Test with multiple tool calls
- [ ] Test with text + tool calls
- [ ] Test with VSCode Copilot Chat client
- [ ] Add error handling for invalid tool arguments
- [ ] Add unit tests for streaming logic
- [ ] Document streaming format in README
- [ ] Add configuration for argument streaming granularity (single vs character)

### 5.11 Expected Impact

**Before Fix**:

- ❌ VSCode SSE parser may fail to buffer tool calls correctly
- ❌ Tool calls may not trigger properly
- ❌ `copilotToolCalls` deltas may be missing or malformed
- ❌ Agent loop may not detect tool requests

**After Fix**:

- ✅ VSCode correctly parses incremental tool call deltas
- ✅ `beginToolCalls` marker detected automatically by parser
- ✅ `copilotToolCalls` assembled correctly after buffering
- ✅ Tool invocation triggered reliably
- ✅ Full agent workflow with iterative tool calling works
- ✅ Streaming UX matches real OpenAI behavior

**Success Metric**: VSCode Copilot Chat successfully invokes tools and iterates through multi-step tasks without errors.

---

## 6. Tool Result Handling {#tool-result-handling}

### 6.1 Overview

After VSCode invokes tools locally, it sends back the results in a subsequent request with `role: "tool"` messages. Our OAI service must correctly detect these tool result messages, extract the outputs, format them for Outlier platform, and maintain conversation context to continue the agent loop.

**Critical Requirements**:

1. **Detect tool role messages** in incoming request
2. **Extract tool results** (tool_call_id, tool name, result content)
3. **Format results for Outlier** using template system
4. **Preserve conversation_id** across tool execution rounds
5. **Continue agent loop** until final answer or max rounds reached

### 6.2 Understanding VSCode Tool Result Format

#### 6.2.1 Tool Role Message Structure

When VSCode invokes a tool and gets a result, it sends a new request with the complete conversation history including:

1. Original user message
2. Assistant message with tool_calls
3. Tool result messages (one per tool call)

**Example Request from VSCode (OpenAI Format)**:

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "system",
      "content": "You are Copilot, an AI coding assistant. Workspace: /home/user/project"
    },
    {
      "role": "user",
      "content": "<context>...</context>\n<userRequest>Read README.md and summarize it</userRequest>"
    },
    {
      "role": "assistant",
      "content": "I'll read that file for you.",
      "tool_calls": [
        {
          "id": "call_abc123xyz",
          "type": "function",
          "function": {
            "name": "read_file",
            "arguments": "{\"path\":\"README.md\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123xyz",
      "name": "read_file",
      "content": "# My Project\n\nThis is a sample README file.\n\n## Installation\n\nRun `npm install` to install dependencies.\n\n## Usage\n\nStart the server with `npm start`."
    }
  ],
  "tools": [...],
  "stream": true
}
```

**Key Fields in Tool Message**:

- `role`: Always `"tool"`
- `tool_call_id`: Links to the `id` from assistant's `tool_calls` array
- `name`: The tool name (e.g., `"read_file"`)
- `content`: The tool result (string or structured content)

#### 6.2.2 Multiple Tool Results

When multiple tools are called, each gets its own tool message:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Add multiply to test.js and jokes to server.js"
    },
    {
      "role": "assistant",
      "content": "I'll make both changes.",
      "tool_calls": [
        {
          "id": "call_001",
          "type": "function",
          "function": {
            "name": "edit_file",
            "arguments": "{\"filePath\":\"test.js\",\"code\":\"...\"}"
          }
        },
        {
          "id": "call_002",
          "type": "function",
          "function": {
            "name": "edit_file",
            "arguments": "{\"filePath\":\"server.js\",\"code\":\"...\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_001",
      "name": "edit_file",
      "content": "Successfully edited test.js - Added multiply function"
    },
    {
      "role": "tool",
      "tool_call_id": "call_002",
      "name": "edit_file",
      "content": "Successfully edited server.js - Added dad jokes collection"
    }
  ]
}
```

**Important**: Tool messages always come AFTER the assistant message that made the tool calls.

#### 6.2.3 Content Formats

Tool result content can be:

**Simple String** (most common):

```json
{
  "role": "tool",
  "content": "# My Project\n\nThis is the README content..."
}
```

**Structured Content** (list of parts):

```json
{
  "role": "tool",
  "content": [
    {
      "type": "text",
      "text": "Found 3 TODO items:\n1. src/main.ts:45 - TODO: Implement error handling"
    }
  ]
}
```

**Error Content** (when tool invocation fails):

```json
{
  "role": "tool",
  "content": "Error: File not found - README.md does not exist in workspace"
}
```

### 6.3 Detection Logic in wormhole-oai.py

#### 6.3.1 Current Detection Implementation

**Location**: `wormhole-oai.py`, lines 252-299 (message parsing loop)

**Current Code**:

```python
for i, msg in enumerate(messages):
    role = msg.get("role")
    content = msg.get("content", "")

    if role == "system":
        raw_system = content
        # ... extract context

    elif role == "user":
        raw_user = content
        # ... extract context, attachments, userRequest

    elif role == "assistant":
        assistant_content = msg.get("content", "")
        if assistant_content and agent_workflow.has_final_answer_marker(assistant_content):
            last_assistant_had_final_answer = True
        else:
            last_assistant_had_final_answer = False

    elif role == "tool":
        has_tool_results = True  # Flag set when tool messages detected
```

**Current Routing Logic** (lines 311-348):

```python
has_assistant_messages = any(msg.get("role") == "assistant" for msg in messages)
is_new_conversation = not has_assistant_messages

if tools and (not has_tool_results or last_assistant_had_final_answer):
    # NEW tool request
    clean_text, tool_calls, conversation_id = await agent_workflow.handle_initial_tool_request(...)
else:
    if has_tool_results and not last_assistant_had_final_answer:
        # TOOL RESPONSE continuation
        clean_text, tool_calls, conversation_id = await agent_workflow.handle_tool_response(model, messages, raw_system)
    else:
        # Simple message
        clean_text, tool_calls, conversation_id = await agent_workflow.handle_simple_user_message(...)
```

**Key Detection Points**:

1. ✅ **Flag `has_tool_results`**: Set to `True` when any `role == "tool"` message found
2. ✅ **Check `last_assistant_had_final_answer`**: Prevents tool response handling if agent already gave final answer
3. ✅ **Route to `handle_tool_response()`**: When `has_tool_results == True` AND no final answer

**What's Working**:

- ✅ Correctly detects presence of tool messages
- ✅ Routes to appropriate handler
- ✅ Prevents re-handling after final answer

**What's Missing**:

- ❌ Doesn't extract tool result details during detection
- ❌ Doesn't validate tool_call_id linkage
- ❌ Doesn't distinguish between tool success/failure

#### 6.3.2 Enhanced Detection Logic

**Proposed Enhancement**:

```python
# In chat_completions() function, replace tool detection section

# Enhanced tool result detection and extraction
tool_results_data = []  # List of {tool_call_id, name, content, success}
last_assistant_msg = None
last_assistant_had_final_answer = False

for i, msg in enumerate(messages):
    role = msg.get("role")
    content = msg.get("content", "")

    if role == "system":
        raw_system = content
        # ... existing context extraction

    elif role == "user":
        raw_user = content
        # ... existing extraction logic

    elif role == "assistant":
        assistant_content = msg.get("content", "")
        last_assistant_msg = msg  # Store reference to last assistant message

        if assistant_content and agent_workflow.has_final_answer_marker(assistant_content):
            last_assistant_had_final_answer = True
        else:
            last_assistant_had_final_answer = False

    elif role == "tool":
        # Extract tool result details
        tool_call_id = msg.get("tool_call_id", "")
        tool_name = msg.get("name", "unknown_tool")
        tool_content = msg.get("content", "")

        # Detect if this is an error result
        is_error = isinstance(tool_content, str) and tool_content.lower().startswith("error:")

        # Normalize content to string
        if isinstance(tool_content, list):
            # Structured content - extract text parts
            text_parts = [
                part.get("text", "") if isinstance(part, dict) and part.get("type") == "text" else str(part)
                for part in tool_content
            ]
            tool_content = "\n".join(text_parts)
        elif not isinstance(tool_content, str):
            tool_content = str(tool_content)

        tool_results_data.append({
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": tool_content,
            "success": not is_error
        })

# Set flag for routing logic
has_tool_results = len(tool_results_data) > 0

print(f"[Tool Detection] Found {len(tool_results_data)} tool result(s)")
for tr in tool_results_data:
    print(f"  - {tr['name']} (id: {tr['tool_call_id'][:10]}...) - {'SUCCESS' if tr['success'] else 'ERROR'}")
```

**Benefits**:

1. ✅ **Captures all tool result metadata** (id, name, content, success status)
2. ✅ **Normalizes content format** (list → string)
3. ✅ **Detects errors** by checking for "Error:" prefix
4. ✅ **Provides detailed logging** for debugging
5. ✅ **Stores last assistant message** for later correlation

### 6.4 Tool Result Correlation with Tool Calls

#### 6.4.1 Matching Tool Results to Tool Calls

**Challenge**: Link tool results back to the original tool calls made by the assistant.

**Current Implementation** (`agent_workflow.py`, `handle_tool_response()`, lines 176-236):

```python
async def handle_tool_response(self, model, messages, raw_system):
    print(f"[Agent] handle_tool_response: model={model}, messages={len(messages)}")

    context = extract_context_tag(raw_system)

    tool_output_parts = []
    last_assistant_msg = None

    # Find last assistant message with tool calls
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            last_assistant_msg = msg
            break

    if last_assistant_msg:
        tool_calls_in_msg = last_assistant_msg.get("tool_calls", [])
        for tc in tool_calls_in_msg:
            func = tc.get("function", {})
            tool_output_parts.append(
                f"You called: {func.get('name')}({func.get('arguments')})"
            )

    # Collect tool result messages that come after last assistant
    collecting_responses = False
    for msg in messages:
        if msg == last_assistant_msg:
            collecting_responses = True
            continue
        if collecting_responses and msg.get("role") == "tool":
            tool_name = msg.get("name", "unknown_tool")
            content = msg.get("content", "")
            tool_output_parts.append(f"Tool '{tool_name}' returned: {content}")

    tool_output = "\n\n".join(tool_output_parts)
    # ... send to Outlier
```

**Analysis**:

- ✅ **Finds last assistant message** with tool calls
- ✅ **Extracts tool call details** (name, arguments)
- ✅ **Collects tool results** that follow the assistant message
- ✅ **Combines into single prompt** for Outlier
- ⚠️ **No validation** of tool_call_id linkage (assumes order-based matching)
- ⚠️ **No error handling** for missing/extra results

#### 6.4.2 Enhanced Correlation Logic

**Proposed Enhancement**:

```python
async def handle_tool_response(self, model, messages, raw_system):
    print(f"[Agent] handle_tool_response: model={model}, messages={len(messages)}")

    context = extract_context_tag(raw_system)

    # Step 1: Find last assistant message with tool calls
    last_assistant_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            last_assistant_msg = msg
            break

    if not last_assistant_msg:
        print("[Agent] ERROR: No assistant message with tool calls found")
        return None, None, None

    # Step 2: Build map of tool calls by ID
    tool_calls_map = {}  # {tool_call_id: {name, arguments}}
    for tc in last_assistant_msg.get("tool_calls", []):
        call_id = tc.get("id", "")
        func = tc.get("function", {})
        tool_calls_map[call_id] = {
            "name": func.get("name", "unknown"),
            "arguments": func.get("arguments", "{}")
        }

    print(f"[Agent] Expecting results for {len(tool_calls_map)} tool call(s)")

    # Step 3: Find tool result messages after assistant message
    tool_results_map = {}  # {tool_call_id: {name, content, success}}
    collecting_results = False

    for msg in messages:
        if msg == last_assistant_msg:
            collecting_results = True
            continue

        if collecting_results and msg.get("role") == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            tool_name = msg.get("name", "unknown_tool")
            content = msg.get("content", "")

            # Normalize content
            if isinstance(content, list):
                text_parts = [
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                ]
                content = "\n".join(text_parts)
            elif not isinstance(content, str):
                content = str(content)

            # Detect success/error
            is_error = content.lower().startswith("error:")

            tool_results_map[tool_call_id] = {
                "name": tool_name,
                "content": content,
                "success": not is_error
            }

    print(f"[Agent] Received {len(tool_results_map)} tool result(s)")

    # Step 4: Validate and match results to calls
    matched_results = []
    unmatched_calls = []

    for call_id, call_info in tool_calls_map.items():
        if call_id in tool_results_map:
            result_info = tool_results_map[call_id]
            matched_results.append({
                "call_id": call_id,
                "call_name": call_info["name"],
                "call_arguments": call_info["arguments"],
                "result_name": result_info["name"],
                "result_content": result_info["content"],
                "success": result_info["success"]
            })
            print(f"[Agent] ✓ Matched {call_info['name']} -> {len(result_info['content'])} chars")
        else:
            unmatched_calls.append({
                "call_id": call_id,
                "name": call_info["name"]
            })
            print(f"[Agent] ✗ No result for {call_info['name']} (id: {call_id})")

    # Step 5: Warn about unmatched results
    unmatched_result_ids = set(tool_results_map.keys()) - set(tool_calls_map.keys())
    if unmatched_result_ids:
        print(f"[Agent] WARNING: {len(unmatched_result_ids)} unmatched result(s) - may be from previous round")

    # Step 6: Handle missing results
    if unmatched_calls:
        print(f"[Agent] WARNING: {len(unmatched_calls)} tool call(s) without results")
        # Add placeholder results for missing tools
        for unmatched in unmatched_calls:
            matched_results.append({
                "call_id": unmatched["call_id"],
                "call_name": unmatched["name"],
                "call_arguments": "{}",
                "result_name": unmatched["name"],
                "result_content": "Error: No result received for this tool call",
                "success": False
            })

    # Step 7: Format tool output for Outlier
    tool_output_parts = []

    for result in matched_results:
        # Add tool call description
        tool_output_parts.append(
            f"Tool Call: {result['call_name']}({result['call_arguments']})"
        )

        # Add result with status indicator
        status = "✓ SUCCESS" if result['success'] else "✗ ERROR"
        tool_output_parts.append(
            f"Result [{status}]: {result['result_content']}"
        )
        tool_output_parts.append("---")  # Separator

    tool_output = "\n\n".join(tool_output_parts)

    # Step 8: Compose prompt and send to Outlier
    prompt = self.composer.compose_tool_response(tool_output, context)
    system_message = self.composer.get_system()

    conversation_id, _ = await self.get_or_create_conversation(model, prompt, system_message)
    if not conversation_id:
        print("[Agent] Failed to get conversation for tool response")
        return None, None, None

    response_text, _ = await self.send_to_outlier(
        conversation_id, prompt, model, system_message
    )

    if response_text is None:
        clean_text = "Error: Failed to get response from model"
        tool_calls = None
    elif self.has_final_answer_marker(response_text):
        clean_text = self.extract_final_answer(response_text)
        tool_calls = None
    else:
        clean_text, tool_call = self.parse_tool_call(response_text)
        tool_calls = [tool_call] if tool_call else None

    return clean_text, tool_calls, conversation_id
```

**Key Improvements**:

1. ✅ **ID-based matching** instead of order-based
2. ✅ **Validates all results received** and warns on mismatches
3. ✅ **Handles missing results** with error placeholders
4. ✅ **Detects success/error status** in results
5. ✅ **Detailed logging** at each step
6. ✅ **Formats output clearly** with status indicators

### 6.5 Formatting Tool Results for Outlier

#### 6.5.1 Template System Integration

**Current Template** (`agent_prompts.yaml`, lines 154-167):

```yaml
tool_response: |
  {% if context %}
  {{ context }}
  ---
  {% endif %}

  {{ tool_output }}

  ---

  Now provide your final answer or call another tool if needed.

  If this is your final answer, use:
  <invoke name="final_answer">
  <parameter name="answer">your answer here</parameter>
  </invoke>
```

**Template Variables**:

- `context`: Workspace context (optional)
- `tool_output`: Formatted tool results string

**Example Rendered Prompt** (with enhanced formatting):

```
<context>
Workspace: /home/user/project
Open files: test.js, server.js
Git branch: main
</context>

---

Tool Call: read_file({"path":"README.md"})

Result [✓ SUCCESS]: # My Project

This is a sample README file.

## Installation

Run `npm install` to install dependencies.

## Usage

Start the server with `npm start`.

---

Tool Call: edit_file({"filePath":"test.js","code":"function multiply(a,b){return a*b;}"})

Result [✓ SUCCESS]: Successfully edited test.js - Added multiply function

---

Now provide your final answer or call another tool if needed.

If this is your final answer, use:
<invoke name="final_answer">
<parameter name="answer">your answer here</parameter>
</invoke>
```

#### 6.5.2 Enhanced Formatting Options

**Option A: Simple Format** (current):

```
Tool 'read_file' returned: [content]
Tool 'edit_file' returned: [content]
```

**Option B: Detailed Format** (proposed):

```
Tool Call: read_file({"path":"README.md"})
Result [✓ SUCCESS]: [content]
---
Tool Call: edit_file({"filePath":"test.js","code":"..."})
Result [✓ SUCCESS]: [content]
---
```

**Option C: Conversational Format** (natural language):

```
You called read_file with path="README.md" and it returned:
[content]

Then you called edit_file for test.js and successfully made the edit:
[content]

What would you like to do next?
```

**Recommendation**: Use **Option B (Detailed Format)** because:

- ✅ Shows both call and result clearly
- ✅ Includes success/error status
- ✅ Maintains structure for LLM parsing
- ✅ Easier to debug
- ✅ Better than conversational (less tokens)

#### 6.5.3 Implementation in template_composer.py

**Current `compose_tool_response()` method** (lines 65-73):

```python
def compose_tool_response(self, tool_output, context=""):
    variables = {
        "system_content": self.get_system(),
        "tool_output": tool_output,
        "context": context,
    }
    template_text = self.templates.get("tool_response", "")
    return populate_template(template_text, variables)
```

**Status**: ✅ Already correct - just needs better `tool_output` formatting from caller

### 6.6 Conversation Context Preservation

#### 6.6.1 Conversation ID Management

**Current Implementation** (`agent_workflow.py`):

**Global State**:

```python
# In wormhole-oai.py
active_conversation_id = None

def set_active_conversation(conversation_id):
    global active_conversation_id
    active_conversation_id = conversation_id
```

**Agent Workflow Callbacks**:

```python
# In AgentWorkflow.__init__
def __init__(self, get_conversation_callback, set_conversation_callback, log_callback):
    self.get_conversation_id = get_conversation_callback
    self.set_conversation_id = set_conversation_callback
    self.log_callback = log_callback
```

**Conversation Retrieval**:

```python
async def get_or_create_conversation(self, model, first_prompt=None, first_system=None):
    conversation_id = self.get_conversation_id()

    if conversation_id:
        print(f"[Agent Workflow] Using existing conversation: {conversation_id}")
        return conversation_id, None

    # Create new conversation if none exists
    input_data = {
        "prompt": first_prompt or "Hello",
        "model": model,
        "systemMessage": first_system or "",
    }

    result = await send_script_async("create_conversation.js", input_data)
    # ... parse result and cache conversation_id
```

**How It Works**:

1. ✅ **First request**: No conversation ID exists → create new conversation
2. ✅ **Tool result request**: Conversation ID cached → reuse existing conversation
3. ✅ **Subsequent rounds**: Same conversation ID throughout
4. ✅ **New user query**: Reset conversation ID → start fresh

**Key Insight**: Conversation ID is **global state** tied to the HTTP request lifecycle, NOT the WebSocket connection.

#### 6.6.2 Conversation ID Flow Through Tool Rounds

**Round 1 (Initial Request)**:

```
User: "Read README.md"
  ↓
create conversation (ID: "conv_123")
  ↓
Send prompt to Outlier
  ↓
Outlier: "I'll read the file" + tool_calls
  ↓
Return to VSCode with tool_calls
  ↓
active_conversation_id = "conv_123"  (cached)
```

**Round 2 (Tool Results)**:

```
VSCode sends tool results
  ↓
Detect has_tool_results = True
  ↓
get_or_create_conversation() → returns "conv_123" (from cache)
  ↓
Format tool results
  ↓
Send to Outlier using "conv_123"
  ↓
Outlier: "The README contains..." (final answer)
  ↓
Return to VSCode
  ↓
Conversation complete
```

**Round 3+ (More Tool Calls)**:

```
If Outlier makes more tool calls:
  ↓
Return tool_calls to VSCode
  ↓
VSCode invokes tools
  ↓
VSCode sends new tool results
  ↓
get_or_create_conversation() → "conv_123" (still cached)
  ↓
Continue loop...
```

**Conversation Reset** (New User Message):

```
User starts new query (no assistant messages in history)
  ↓
is_new_conversation = True
  ↓
active_conversation_id = None  (reset in chat_completions())
  ↓
create new conversation
```

#### 6.6.3 Handling Conversation State Across Requests

**Challenge**: HTTP is stateless, but conversation must persist across multiple tool rounds.

**Current Solution**: Global variable `active_conversation_id`

**Limitations**:

- ❌ Not thread-safe (but Python GIL makes it mostly safe)
- ❌ Shared across concurrent requests (could cause conflicts)
- ❌ Lost on server restart

**Better Solution** (Future Enhancement):

```python
# Use session-based storage
from fastapi import Request, Response
from starlette.middleware.sessions import SessionMiddleware

# Add session middleware
app.add_middleware(SessionMiddleware, secret_key="your-secret-key")

# Store conversation ID in session
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    # Get conversation ID from session
    conversation_id = request.session.get("conversation_id")

    if is_new_conversation:
        conversation_id = None
        request.session["conversation_id"] = None

    # ... process request ...

    if new_conversation_created:
        request.session["conversation_id"] = new_conversation_id

    return response
```

**For Current Implementation**: Global variable is acceptable since:

1. ✅ Requests are processed sequentially by VSCode
2. ✅ Single user (developer) per OAI service instance
3. ✅ Conversation resets naturally on new queries

### 6.7 Complete Tool Result Handling Flow

#### 6.7.1 Step-by-Step Flow

**Step 1: VSCode Sends Tool Results**

```json
POST /v1/chat/completions
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Read README.md"},
    {"role": "assistant", "content": "I'll read it", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "call_123", "name": "read_file", "content": "# My Project..."}
  ],
  "tools": [...],
  "stream": true
}
```

**Step 2: Detection in wormhole-oai.py**

```python
# Parse messages
for msg in messages:
    if msg.get("role") == "tool":
        has_tool_results = True
        tool_results_data.append({
            "tool_call_id": msg.get("tool_call_id"),
            "name": msg.get("name"),
            "content": msg.get("content"),
            "success": not msg.get("content", "").lower().startswith("error:")
        })

# Route to tool response handler
if has_tool_results and not last_assistant_had_final_answer:
    clean_text, tool_calls, conversation_id = await agent_workflow.handle_tool_response(
        model, messages, raw_system
    )
```

**Step 3: Correlation in agent_workflow.py**

```python
# Find last assistant message
last_assistant_msg = find_last_assistant_with_tool_calls(messages)

# Build maps
tool_calls_map = {tc["id"]: tc for tc in last_assistant_msg["tool_calls"]}
tool_results_map = {tr.tool_call_id: tr for tr in collect_tool_results(messages, last_assistant_msg)}

# Match results to calls
matched_results = match_tool_results(tool_calls_map, tool_results_map)
```

**Step 4: Formatting**

```python
# Format tool output
tool_output_parts = []
for result in matched_results:
    tool_output_parts.append(f"Tool Call: {result['call_name']}({result['call_arguments']})")
    status = "✓ SUCCESS" if result['success'] else "✗ ERROR"
    tool_output_parts.append(f"Result [{status}]: {result['result_content']}")
    tool_output_parts.append("---")

tool_output = "\n\n".join(tool_output_parts)
```

**Step 5: Prompt Composition**

```python
# Compose prompt using template
prompt = self.composer.compose_tool_response(tool_output, context)

# Example rendered prompt:
"""
<context>
Workspace: /home/user/project
</context>

---

Tool Call: read_file({"path":"README.md"})

Result [✓ SUCCESS]: # My Project

This is a sample README file.

---

Now provide your final answer or call another tool if needed.
"""
```

**Step 6: Send to Outlier**

```python
# Get or reuse conversation
conversation_id, _ = await self.get_or_create_conversation(model, prompt, system_message)

# Send prompt to Outlier
response_text, _ = await self.send_to_outlier(conversation_id, prompt, model, system_message)
```

**Step 7: Parse Response**

```python
# Check for final answer
if self.has_final_answer_marker(response_text):
    clean_text = self.extract_final_answer(response_text)
    tool_calls = None
else:
    # Parse for more tool calls
    clean_text, tool_call = self.parse_tool_call(response_text)
    tool_calls = [tool_call] if tool_call else None
```

**Step 8: Return to wormhole-oai.py**

```python
# Stream response back to VSCode
if stream:
    async def generate():
        # Role delta
        yield role_chunk

        # Text content (if any)
        if clean_text:
            for char in clean_text:
                yield text_chunk

        # Tool calls (if any)
        if tool_calls:
            for tool_call in tool_calls:
                yield tool_call_chunks

        # Completion
        yield final_chunk
        yield "[DONE]"

    return StreamingResponse(generate())
```

**Step 9: Loop Continuation**

- **If tool_calls exist**: VSCode invokes tools → sends new tool results → repeat from Step 1
- **If no tool_calls**: VSCode displays final answer → conversation complete

#### 6.7.2 Complete Example with Multiple Rounds

**Initial Request**:

```
User: "Read README.md and create SUMMARY.md with key points"
```

**Round 1 Response (from Outlier)**:

```
I'll read the README first.
<invoke name="read_file">
<parameter name="path">README.md</parameter>
</invoke>
```

**Round 2 Request (VSCode sends tool result)**:

```json
{
  "messages": [
    {"role": "user", "content": "Read README.md and create SUMMARY.md"},
    {"role": "assistant", "content": "I'll read the README first.", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "call_001", "content": "# My Project\n\nInstall: npm install\nUsage: npm start"}
  ]
}
```

**Round 2 Prompt to Outlier**:

```
Tool Call: read_file({"path":"README.md"})

Result [✓ SUCCESS]: # My Project

Install: npm install
Usage: npm start

---

Now provide your final answer or call another tool if needed.
```

**Round 2 Response (from Outlier)**:

```
Now I'll create the summary file.
<invoke name="create_file">
<parameter name="path">SUMMARY.md</parameter>
<parameter name="content"># Summary

- Install dependencies with npm install
- Start server with npm start
</parameter>
</invoke>
```

**Round 3 Request (VSCode sends second tool result)**:

```json
{
  "messages": [
    {"role": "user", "content": "Read README.md and create SUMMARY.md"},
    {"role": "assistant", "content": "I'll read the README first.", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "call_001", "content": "# My Project..."},
    {"role": "assistant", "content": "Now I'll create the summary file.", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "call_002", "content": "Created SUMMARY.md successfully"}
  ]
}
```

**Round 3 Prompt to Outlier**:

```
Tool Call: create_file({"path":"SUMMARY.md","content":"..."})

Result [✓ SUCCESS]: Created SUMMARY.md successfully

---

Now provide your final answer or call another tool if needed.
```

**Round 3 Response (from Outlier)**:

```
<invoke name="final_answer">
<parameter name="answer">I've completed both tasks:
1. ✓ Read README.md
2. ✓ Created SUMMARY.md with the key points

The summary file is now available in your workspace.</parameter>
</invoke>
```

**Final Response to VSCode**:

```
I've completed both tasks:
1. ✓ Read README.md
2. ✓ Created SUMMARY.md with the key points

The summary file is now available in your workspace.
```

**Loop Terminates**: No tool calls in final response.

### 6.8 Error Handling

#### 6.8.1 Missing Tool Results

**Scenario**: Assistant made 2 tool calls, but only 1 tool result received.

**Detection**:

```python
unmatched_calls = []
for call_id, call_info in tool_calls_map.items():
    if call_id not in tool_results_map:
        unmatched_calls.append(call_id)
        print(f"[Agent] ✗ No result for {call_info['name']} (id: {call_id})")
```

**Handling**:

```python
# Add placeholder error result
for unmatched in unmatched_calls:
    matched_results.append({
        "call_id": unmatched["call_id"],
        "call_name": unmatched["name"],
        "result_content": "Error: No result received for this tool call",
        "success": False
    })
```

**Prompt to Outlier**:

```
Tool Call: read_file({"path":"README.md"})
Result [✓ SUCCESS]: # My Project...

Tool Call: edit_file({"path":"test.js"})
Result [✗ ERROR]: Error: No result received for this tool call

---
```

**Expected Behavior**: Outlier may retry the failed tool or ask user for clarification.

#### 6.8.2 Tool Execution Errors

**Scenario**: Tool was invoked but returned an error.

**Detection**:

```python
is_error = tool_content.lower().startswith("error:")
```

**Example Error Content**:

```
Error: File not found - README.md does not exist in workspace
```

**Formatted Output**:

```
Tool Call: read_file({"path":"README.md"})
Result [✗ ERROR]: Error: File not found - README.md does not exist in workspace
```

**Expected Behavior**: Outlier should recognize the error and either:

1. Try alternative approach
2. Ask user for correct path
3. Provide final answer explaining the issue

#### 6.8.3 Extra Tool Results

**Scenario**: More tool results than tool calls (duplicate results from previous round).

**Detection**:

```python
unmatched_result_ids = set(tool_results_map.keys()) - set(tool_calls_map.keys())
if unmatched_result_ids:
    print(f"[Agent] WARNING: {len(unmatched_result_ids)} unmatched result(s)")
```

**Handling**: Ignore extra results (don't include in prompt).

**Reason**: VSCode may be sending stale results from previous rounds.

#### 6.8.4 No Last Assistant Message

**Scenario**: Tool results exist but no assistant message with tool_calls found.

**Detection**:

```python
if not last_assistant_msg:
    print("[Agent] ERROR: No assistant message with tool calls found")
    return None, None, None
```

**Handling**: Return error to client.

**Likely Cause**: Malformed request or conversation state corruption.

### 6.9 Testing Strategy

#### 6.9.1 Unit Tests

**Test File**: `/services/oai/test_tool_results.py`

```python
import pytest
from agent_workflow import AgentWorkflow

def test_tool_result_detection():
    """Test detection of tool messages in request"""
    messages = [
        {"role": "user", "content": "Read file"},
        {"role": "assistant", "content": "I'll read it", "tool_calls": [...]},
        {"role": "tool", "tool_call_id": "call_123", "name": "read_file", "content": "File content"}
    ]

    # Count tool messages
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["name"] == "read_file"

def test_tool_result_correlation():
    """Test matching tool results to tool calls"""
    tool_calls_map = {
        "call_001": {"name": "read_file", "arguments": '{"path":"README.md"}'}
    }
    tool_results_map = {
        "call_001": {"name": "read_file", "content": "File content", "success": True}
    }

    # Should match successfully
    matched = match_tool_results(tool_calls_map, tool_results_map)
    assert len(matched) == 1
    assert matched[0]["call_id"] == "call_001"
    assert matched[0]["success"] == True

def test_missing_tool_result():
    """Test handling of missing tool result"""
    tool_calls_map = {
        "call_001": {"name": "read_file"},
        "call_002": {"name": "edit_file"}
    }
    tool_results_map = {
        "call_001": {"name": "read_file", "content": "OK", "success": True}
        # call_002 missing
    }

    matched, unmatched = match_tool_results_with_validation(tool_calls_map, tool_results_map)
    assert len(matched) == 1
    assert len(unmatched) == 1
    assert unmatched[0]["call_id"] == "call_002"

def test_error_result_detection():
    """Test detection of error in tool result"""
    content = "Error: File not found - README.md does not exist"
    is_error = content.lower().startswith("error:")
    assert is_error == True

    content = "Successfully read file"
    is_error = content.lower().startswith("error:")
    assert is_error == False

def test_tool_output_formatting():
    """Test formatting of tool results for Outlier"""
    matched_results = [
        {
            "call_name": "read_file",
            "call_arguments": '{"path":"README.md"}',
            "result_content": "# My Project",
            "success": True
        }
    ]

    output = format_tool_output(matched_results)
    assert "Tool Call: read_file" in output
    assert "Result [✓ SUCCESS]" in output
    assert "# My Project" in output
```

#### 6.9.2 Integration Tests

**Test Scenario 1: Single Tool Round**

```python
async def test_single_tool_round():
    """Test complete flow with one tool call and result"""
    # Step 1: Initial request with tool
    response1 = await client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "Read README.md"}],
        "tools": [{"type": "function", "function": {"name": "read_file", ...}}],
        "stream": False
    })

    assert response1["choices"][0]["finish_reason"] == "tool_calls"
    tool_call = response1["choices"][0]["message"]["tool_calls"][0]
    assert tool_call["function"]["name"] == "read_file"

    # Step 2: Send tool result
    response2 = await client.post("/v1/chat/completions", json={
        "messages": [
            {"role": "user", "content": "Read README.md"},
            {"role": "assistant", "content": "I'll read it", "tool_calls": [tool_call]},
            {"role": "tool", "tool_call_id": tool_call["id"], "content": "# My Project"}
        ],
        "tools": [...],
        "stream": False
    })

    assert response2["choices"][0]["finish_reason"] == "stop"
    assert "My Project" in response2["choices"][0]["message"]["content"]
```

**Test Scenario 2: Multiple Tool Rounds**

```python
async def test_multiple_tool_rounds():
    """Test flow with multiple tool call iterations"""
    conversation_history = [
        {"role": "user", "content": "Read README and create summary"}
    ]

    for round_num in range(3):  # Max 3 rounds
        response = await client.post("/v1/chat/completions", json={
            "messages": conversation_history,
            "tools": [...],
            "stream": False
        })

        # Add assistant response to history
        conversation_history.append(response["choices"][0]["message"])

        # If tool calls, simulate execution and add results
        if response["choices"][0]["finish_reason"] == "tool_calls":
            tool_calls = response["choices"][0]["message"]["tool_calls"]
            for tc in tool_calls:
                # Simulate tool execution
                result = simulate_tool_execution(tc)
                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["function"]["name"],
                    "content": result
                })
        else:
            # No more tool calls, conversation complete
            break

    # Final response should be text-only
    assert response["choices"][0]["finish_reason"] == "stop"
```

#### 6.9.3 Manual Testing Checklist

- [ ] Single tool call → result → final answer
- [ ] Multiple tool calls in one response → all results → final answer
- [ ] Tool call → result → another tool call → result → final answer
- [ ] Tool call with error result → agent handles error gracefully
- [ ] Missing tool result → agent uses placeholder error
- [ ] Extra tool results → agent ignores extras
- [ ] Conversation ID persists across tool rounds
- [ ] New conversation resets ID properly
- [ ] Tool output formatting is clear and readable
- [ ] VSCode UI shows tool invocations correctly

### 6.10 Code Changes Summary

#### 6.10.1 Changes to wormhole-oai.py

**Location**: Lines 252-299 (message parsing)

**Change**: Enhanced tool result detection and extraction

```python
# BEFORE:
elif role == "tool":
    has_tool_results = True

# AFTER:
elif role == "tool":
    tool_call_id = msg.get("tool_call_id", "")
    tool_name = msg.get("name", "unknown_tool")
    tool_content = msg.get("content", "")

    # Normalize content
    if isinstance(tool_content, list):
        text_parts = [...]
        tool_content = "\n".join(text_parts)

    is_error = isinstance(tool_content, str) and tool_content.lower().startswith("error:")

    tool_results_data.append({
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "content": tool_content,
        "success": not is_error
    })

has_tool_results = len(tool_results_data) > 0
```

#### 6.10.2 Changes to agent_workflow.py

**Location**: `handle_tool_response()` method (lines 176-236)

**Change**: Enhanced correlation and formatting

```python
# BEFORE:
tool_output_parts = []
for msg in messages:
    if msg.get("role") == "tool":
        tool_output_parts.append(f"Tool '{msg['name']}' returned: {msg['content']}")

# AFTER:
# Step 1: Build tool calls map
tool_calls_map = {...}

# Step 2: Build tool results map
tool_results_map = {...}

# Step 3: Match and validate
matched_results = match_tool_results(tool_calls_map, tool_results_map)

# Step 4: Format with status indicators
tool_output_parts = []
for result in matched_results:
    tool_output_parts.append(f"Tool Call: {result['call_name']}(...)")
    status = "✓ SUCCESS" if result['success'] else "✗ ERROR"
    tool_output_parts.append(f"Result [{status}]: {result['result_content']}")
```

### 6.11 Implementation Checklist

- [ ] Add enhanced tool result detection in wormhole-oai.py
- [ ] Extract tool result metadata (id, name, content, success)
- [ ] Implement ID-based correlation in handle_tool_response()
- [ ] Add validation for missing/extra results
- [ ] Implement enhanced formatting with status indicators
- [ ] Add error handling for missing results
- [ ] Add logging for correlation process
- [ ] Test single tool round flow
- [ ] Test multiple tool rounds flow
- [ ] Test error result handling
- [ ] Test missing result handling
- [ ] Verify conversation ID persistence
- [ ] Document tool result format in README

### 6.12 Expected Impact

**Before Enhancement**:

- ✅ Basic tool result handling works
- ⚠️ Order-based matching (fragile)
- ⚠️ No validation of results
- ⚠️ No error detection
- ⚠️ Limited logging

**After Enhancement**:

- ✅ ID-based matching (robust)
- ✅ Validation of all results
- ✅ Error detection and handling
- ✅ Missing result placeholders
- ✅ Detailed logging at each step
- ✅ Clear status indicators (SUCCESS/ERROR)
- ✅ Better debugging capabilities

**Success Metrics**:

1. ✅ Agent successfully iterates through multiple tool rounds
2. ✅ Tool results correctly formatted and sent to Outlier
3. ✅ Errors in tool execution handled gracefully
4. ✅ Conversation ID persists across all rounds
5. ✅ Final answer provided after all tool executions complete

---

## 7. Step-by-Step Implementation Plan {#implementation-steps}

This section provides a detailed, ordered checklist for implementing all changes to make the OAI service fully compatible with VSCode Copilot Chat expectations.

### 7.1 Phase 1: Preparation & Setup

**Duration**: 1-2 hours  
**Prerequisites**: None  
**Risk Level**: Low

#### Step 1.1: Backup Current Code

```bash
cd /home/niku/Sandbox/outlier_wormhole/services/oai
git checkout -b feature/vscode-copilot-compatibility
git add -A
git commit -m "Backup before VSCode compatibility changes"
```

#### Step 1.2: Create Test Environment

```bash
# Create test script directory
mkdir -p tests/integration
touch tests/integration/test_vscode_requests.py
touch tests/integration/sample_requests.json
```

#### Step 1.3: Document Current Behavior

```bash
# Capture current responses for regression testing
curl -X POST http://localhost:11434/v1/chat/completions \
  -H "Authorization: Bearer $OAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d @tests/integration/sample_requests.json \
  > tests/integration/baseline_responses.json
```

**Success Criteria**:

- ✅ Git branch created
- ✅ Test directories exist
- ✅ Baseline captured

---

### 7.2 Phase 2: Implement Prompt Injection Strategy

**Duration**: 3-4 hours  
**Prerequisites**: Phase 1 complete  
**Risk Level**: Medium  
**Files to Modify**: `wormhole-oai.py`

#### Step 2.1: Add Prompt Injection Function

**Location**: Add before `chat_completions` function (around line 200)

```python
def inject_system_into_user_message(messages):
    """
    Inject all system messages into the first user message.
    Required because Outlier ignores system prompts.

    Returns: Modified messages array with system content injected
    """
    # Find all system messages
    system_messages = [msg for msg in messages if msg.get("role") == "system"]

    # If no system messages, return unchanged
    if not system_messages:
        return messages

    # Check if this is a new conversation (no assistant messages)
    has_assistant = any(msg.get("role") == "assistant" for msg in messages)

    # Only inject on NEW conversations
    if has_assistant:
        return messages

    # Find first user message
    first_user_idx = None
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            first_user_idx = i
            break

    if first_user_idx is None:
        return messages  # No user message found

    # Build injected content
    injected_parts = ["<system_context>"]

    for i, sys_msg in enumerate(system_messages):
        injected_parts.append(f"\n=== System Instructions (Part {i+1}) ===")
        content = sys_msg.get("content", "")
        if isinstance(content, list):
            # Handle structured content
            text_parts = [item.get("text", "") for item in content if item.get("type") == "text"]
            content = "\n".join(text_parts)
        injected_parts.append(content)

    injected_parts.append("\n</system_context>\n\n")

    # Get original user message content
    user_msg = messages[first_user_idx]
    original_content = user_msg.get("content", "")

    if isinstance(original_content, str):
        # Simple string content
        new_content = "".join(injected_parts) + original_content
        messages[first_user_idx]["content"] = new_content
    elif isinstance(original_content, list):
        # Structured content - prepend as first text part
        injection_part = {"type": "text", "text": "".join(injected_parts)}
        messages[first_user_idx]["content"] = [injection_part] + original_content

    # Remove system messages from array (they're now injected)
    messages = [msg for msg in messages if msg.get("role") != "system"]

    print(f"[Prompt Injection] Injected {len(system_messages)} system messages into user prompt")

    return messages
```

**Testing Checkpoint 2.1**:

```python
# Test the function
test_messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello world"}
]
result = inject_system_into_user_message(test_messages)
assert len(result) == 1  # System message removed
assert "<system_context>" in result[0]["content"]
print("✅ Prompt injection function works")
```

#### Step 2.2: Integrate into Request Handler

**Location**: In `chat_completions` function, after line 245 (`messages = body.get("messages", [])`)

```python
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    # ... existing code ...

    messages = body.get("messages", [])

    # INJECT SYSTEM PROMPTS INTO USER MESSAGE
    messages = inject_system_into_user_message(messages)

    stream = body.get("stream", False)
    tools = body.get("tools", [])
    # ... rest of function ...
```

**Testing Checkpoint 2.2**:

- Start server: `python wormhole-oai.py`
- Send test request with system message
- Check logs for "Injected N system messages" message
- Verify Outlier receives injected content in user prompt

**Rollback**: Comment out the injection line if issues occur

---

### 7.3 Phase 3: Fix SSE Streaming Format for Tool Calls

**Duration**: 4-5 hours  
**Prerequisites**: Phase 2 complete  
**Risk Level**: High  
**Files to Modify**: `wormhole-oai.py`

#### Step 3.1: Add Tool Call Parsing Function

**Location**: Add before `chat_completions` function

```python
def parse_all_tool_calls(response_text):
    """
    Parse ALL tool calls from Outlier response.
    Handles multiple <invoke> blocks.

    Returns: (clean_text, list_of_tool_calls)
    """
    import re
    import json
    import uuid

    tool_calls = []
    clean_text = response_text

    # Pattern to match <invoke> blocks
    invoke_pattern = r'<invoke name="([^"]+)">(.*?)</invoke>'
    matches = re.finditer(invoke_pattern, response_text, re.DOTALL)

    for match in matches:
        tool_name = match.group(1)
        params_block = match.group(2)

        # Skip final_answer - that's not a real tool call
        if tool_name == "final_answer":
            continue

        # Parse parameters
        param_pattern = r'<parameter name="([^"]+)">(.*?)</parameter>'
        params = re.findall(param_pattern, params_block, re.DOTALL)
        arguments = {name: value.strip() for name, value in params}

        # Create tool call object
        tool_call = {
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(arguments)
            }
        }
        tool_calls.append(tool_call)

        # Remove this invoke block from clean text
        clean_text = clean_text[:match.start()] + clean_text[match.end():]

    clean_text = clean_text.strip()

    return clean_text, tool_calls
```

**Testing Checkpoint 3.1**:

```python
test_response = '''
I'll help with that.
<invoke name="readFile"><parameter name="path">test.js</parameter></invoke>
<invoke name="createFile"><parameter name="path">new.js</parameter><parameter name="content">code</parameter></invoke>
'''
clean, calls = parse_all_tool_calls(test_response)
assert len(calls) == 2
assert calls[0]["function"]["name"] == "readFile"
assert calls[1]["function"]["name"] == "createFile"
print("✅ Tool call parsing works for multiple calls")
```

#### Step 3.2: Rewrite SSE Streaming Generator

**Location**: Replace the `generate()` function inside `chat_completions` (lines 353-404)

```python
async def generate():
    """
    Generate SSE stream with proper OpenAI-compatible format.
    Supports incremental tool call streaming.
    """
    chunk_id = completion_id

    # Step 1: Send role delta
    first_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "system_fingerprint": None,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant"},
            "logprobs": None,
            "finish_reason": None,
        }],
    }
    yield f"data: {json.dumps(first_chunk)}\n\n"

    # Step 2: Handle tool calls vs text
    if tool_calls:
        # Send beginToolCalls signal
        begin_chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": model,
            "system_fingerprint": None,
            "choices": [{
                "index": 0,
                "delta": {"beginToolCalls": {"toolCallIds": [tc["id"] for tc in tool_calls]}},
                "logprobs": None,
                "finish_reason": None,
            }],
        }
        yield f"data: {json.dumps(begin_chunk)}\n\n"

        # Stream each tool call incrementally
        for idx, tool_call in enumerate(tool_calls):
            # Start of tool call (with id, type, name)
            start_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "system_fingerprint": None,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": idx,
                            "id": tool_call["id"],
                            "type": "function",
                            "function": {
                                "name": tool_call["function"]["name"],
                                "arguments": ""
                            }
                        }]
                    },
                    "logprobs": None,
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(start_chunk)}\n\n"

            # Stream arguments (option 1: single chunk)
            args_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "system_fingerprint": None,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": idx,
                            "function": {
                                "arguments": tool_call["function"]["arguments"]
                            }
                        }]
                    },
                    "logprobs": None,
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(args_chunk)}\n\n"

        finish_reason = "tool_calls"

    elif clean_text:
        # Stream text content character by character
        for char in clean_text:
            chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "system_fingerprint": None,
                "choices": [{
                    "index": 0,
                    "delta": {"content": char},
                    "logprobs": None,
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

        finish_reason = "stop"

    else:
        finish_reason = "stop"

    # Step 3: Send finish chunk
    final_chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "system_fingerprint": None,
        "choices": [{
            "index": 0,
            "delta": {},
            "logprobs": None,
            "finish_reason": finish_reason,
        }],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"

    # Step 4: Stream terminator
    yield "data: [DONE]\n\n"
```

#### Step 3.3: Update Response Processing

**Location**: Before the streaming response (around line 311), update tool call processing

```python
# Before this was done in agent_workflow, now we parse here
if tools and (not has_tool_results or last_assistant_had_final_answer):
    raw_response, _, conversation_id = await agent_workflow.handle_initial_tool_request(
        model, user_request, tools, attachments, context, raw_system, is_first=is_new_conversation
    )

    # Parse response for tool calls
    if raw_response:
        clean_text, tool_calls = parse_all_tool_calls(raw_response)
    else:
        clean_text, tool_calls = None, None
```

**Testing Checkpoint 3.3**:

- Start server
- Send request with tools to VSCode
- Check SSE stream in browser DevTools/Network tab
- Verify: role delta → beginToolCalls → tool_calls with index → finish
- Use curl with `-N` flag to see streaming:

```bash
curl -N -X POST http://localhost:11434/v1/chat/completions \
  -H "Authorization: Bearer $OAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"List files"}],"tools":[...],"stream":true}'
```

**Rollback**: Revert `generate()` function to original

---

### 7.4 Phase 4: Enhance Tool Result Handling

**Duration**: 3-4 hours  
**Prerequisites**: Phases 2 and 3 complete  
**Risk Level**: Medium  
**Files to Modify**: `wormhole-oai.py`, `agent_workflow.py`

#### Step 4.1: Improve Tool Result Detection

**Location**: In `wormhole-oai.py`, enhance message parsing (around line 270)

```python
# Enhanced tool result tracking
tool_results_map = {}  # Map tool_call_id -> result

for i, msg in enumerate(messages):
    role = msg.get("role")
    # ... existing role handling ...

    elif role == "tool":
        has_tool_results = True
        tool_call_id = msg.get("tool_call_id", f"unknown_{i}")
        tool_name = msg.get("name", "unknown_tool")
        content = msg.get("content", "")

        tool_results_map[tool_call_id] = {
            "id": tool_call_id,
            "name": tool_name,
            "content": content,
            "index": i
        }
        print(f"[Tool Result] Detected: {tool_name} (id: {tool_call_id[:8]}...)")
```

#### Step 4.2: Update handle_tool_response

**Location**: In `agent_workflow.py`, modify `handle_tool_response` (line 232)

```python
async def handle_tool_response(self, model, messages, raw_system, tool_results_map=None):
    """
    Enhanced version that uses ID-based matching for tool results.
    """
    print(f"[Agent] handle_tool_response: model={model}, messages={len(messages)}")

    context = extract_context_tag(raw_system)

    # Find the last assistant message with tool calls
    last_assistant_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            last_assistant_msg = msg
            break

    if not last_assistant_msg:
        print("[Agent] ERROR: No assistant message with tool calls found")
        return "Error: No tool calls to respond to", None, None

    tool_calls_in_msg = last_assistant_msg.get("tool_calls", [])

    # Build detailed tool output using ID matching
    tool_output_parts = []

    for tc in tool_calls_in_msg:
        tc_id = tc.get("id")
        func = tc.get("function", {})
        tool_name = func.get("name", "unknown")
        args = func.get("arguments", "{}")

        # Find matching result by ID
        result = tool_results_map.get(tc_id) if tool_results_map else None

        if result:
            status = "SUCCESS"
            content = result["content"]
        else:
            status = "MISSING"
            content = "[Error: Tool result not received]"
            print(f"[Agent] WARNING: Missing result for tool call {tc_id}")

        tool_output_parts.append(
            f"Tool Call: {tool_name}\n"
            f"Arguments: {args}\n"
            f"Status: {status}\n"
            f"Result: {content}\n"
        )

    tool_output = "\n---\n".join(tool_output_parts)

    # Use updated template
    prompt = self.composer.compose_tool_response(tool_output, context)
    system_message = self.composer.get_system()

    # Continue conversation
    conversation_id, _ = await self.get_or_create_conversation(model, prompt, system_message)
    if not conversation_id:
        return None, None, None

    response_text, _ = await self.send_to_outlier(conversation_id, prompt, model, system_message)

    if response_text and self.has_final_answer_marker(response_text):
        clean_text = self.extract_final_answer(response_text)
        tool_calls = None
    else:
        # Parse for potential new tool calls
        clean_text, tool_call = self.parse_tool_call(response_text)
        tool_calls = [tool_call] if tool_call else None

    return clean_text, tool_calls, conversation_id
```

#### Step 4.3: Pass Tool Results Map

**Location**: In `wormhole-oai.py`, update the call (around line 330)

```python
if has_tool_results and not last_assistant_had_final_answer:
    clean_text, tool_calls, conversation_id = await agent_workflow.handle_tool_response(
        model, messages, raw_system, tool_results_map  # ADD THIS PARAMETER
    )
```

**Testing Checkpoint 4.3**:

- Send initial request with tools
- Intercept tool calls
- Send follow-up with tool role messages
- Verify Outlier receives formatted tool results
- Check logs for "Tool Result Detected" messages

**Rollback**: Remove `tool_results_map` parameter, revert to order-based matching

---

### 7.5 Phase 5: Integration & Testing

**Duration**: 4-6 hours  
**Prerequisites**: Phases 2, 3, 4 complete  
**Risk Level**: Low

#### Step 5.1: Unit Tests

Create `tests/test_prompt_injection.py`:

```python
import pytest
from services.oai.wormhole-oai import inject_system_into_user_message

def test_system_injection_simple():
    messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"}
    ]
    result = inject_system_into_user_message(messages)
    assert len(result) == 1
    assert "<system_context>" in result[0]["content"]
    assert "You are helpful" in result[0]["content"]
    assert "Hello" in result[0]["content"]

def test_system_injection_skip_on_continuation():
    messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
        {"role": "user", "content": "More questions"}
    ]
    result = inject_system_into_user_message(messages)
    # Should NOT inject because conversation already started
    assert any(msg.get("role") == "system" for msg in result)
```

Run: `pytest tests/test_prompt_injection.py -v`

#### Step 5.2: Integration Tests with VSCode

**Manual Test Checklist**:

1. ✅ Connect VSCode to OAI service
2. ✅ Send simple text query → Verify response
3. ✅ Send query that should trigger tool call → Verify SSE format
4. ✅ Verify VSCode shows tool call in UI
5. ✅ Execute tool in VSCode → Verify result sent back
6. ✅ Verify final answer received
7. ✅ Test multi-tool scenario (2-3 tool calls)
8. ✅ Test error cases (invalid tool, missing result)

#### Step 5.3: Regression Testing

```bash
# Compare new responses with baseline
python tests/integration/regression_test.py \
  --baseline tests/integration/baseline_responses.json \
  --current http://localhost:11434
```

#### Step 5.4: Performance Testing

Measure latency impact:

```python
import time
import statistics

latencies = []
for i in range(100):
    start = time.time()
    # Send request
    response = make_request()
    latencies.append(time.time() - start)

print(f"Avg latency: {statistics.mean(latencies):.2f}s")
print(f"P95 latency: {statistics.quantiles(latencies, n=20)[18]:.2f}s")
```

**Success Criteria**:

- All tests pass
- Latency increase < 10%
- No regressions in text-only responses

---

### 7.6 Phase 6: Deployment & Monitoring

**Duration**: 1-2 hours  
**Prerequisites**: All phases complete, tests passing  
**Risk Level**: Low

#### Step 6.1: Pre-Deployment Checklist

- [ ] All code reviewed
- [ ] All tests passing
- [ ] Documentation updated
- [ ] Rollback plan documented
- [ ] Monitoring alerts configured

#### Step 6.2: Deployment Steps

```bash
# 1. Stop current service
docker-compose down oai

# 2. Pull latest code
git pull origin feature/vscode-copilot-compatibility

# 3. Rebuild container
docker-compose build oai

# 4. Start with health check
docker-compose up -d oai
docker-compose logs -f oai | grep "URL:"

# 5. Smoke test
curl http://localhost:11434/api/version
```

#### Step 6.3: Post-Deployment Monitoring

Monitor for 24 hours:

- Error rates (should be < 1%)
- Response times (should be within 10% of baseline)
- Tool call success rate (track in logs)
- VSCode connection stability

#### Step 6.4: Rollback Plan

If critical issues detected:

```bash
# 1. Stop service
docker-compose down oai

# 2. Revert to previous version
git checkout main
docker-compose build oai
docker-compose up -d oai

# 3. Verify
curl http://localhost:11434/api/version
```

---

### 7.7 Implementation Timeline

**Total Estimated Time**: 16-24 hours

| Phase                     | Duration | Dependencies  | Risk   |
| ------------------------- | -------- | ------------- | ------ |
| Phase 1: Preparation      | 1-2h     | None          | Low    |
| Phase 2: Prompt Injection | 3-4h     | Phase 1       | Medium |
| Phase 3: SSE Streaming    | 4-5h     | Phase 2       | High   |
| Phase 4: Tool Results     | 3-4h     | Phase 2, 3    | Medium |
| Phase 5: Testing          | 4-6h     | Phase 2, 3, 4 | Low    |
| Phase 6: Deployment       | 1-2h     | All           | Low    |

**Recommended Approach**:

- Implement Phase 2 first, test thoroughly
- Implement Phase 3 separately, test thoroughly
- Implement Phase 4 separately, test thoroughly
- Only after all three work independently, do integration testing

**Critical Success Factors**:

1. Test each phase independently before moving to next
2. Maintain rollback capability at each step
3. Verify with actual VSCode client, not just curl
4. Monitor Outlier logs to verify it receives correct prompts
5. Check VSCode DevTools Network tab to verify SSE format

---

## 8. Testing Strategy {#testing-strategy}

Comprehensive testing approach covered in Phase 5 of implementation plan (Section 7.5). Additional details below:

### 8.1 Unit Tests

**Test File**: `tests/unit/test_oai_service.py`

```python
import pytest
import json
from services.oai import wormhole_oai

class TestPromptInjection:
    def test_inject_system_into_new_conversation(self):
        """System prompt should be injected on new conversations"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "system", "content": "Use tools to complete tasks."},
            {"role": "user", "content": "Hello world"}
        ]
        result = wormhole_oai.inject_system_into_user_message(messages)

        assert len(result) == 1  # Only user message remains
        assert result[0]["role"] == "user"
        assert "<system_context>" in result[0]["content"]
        assert "Part 1" in result[0]["content"]
        assert "Part 2" in result[0]["content"]
        assert "Hello world" in result[0]["content"]

    def test_no_injection_on_continuation(self):
        """System prompt should NOT be injected on continuing conversations"""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "Tell me more"}
        ]
        result = wormhole_oai.inject_system_into_user_message(messages)

        # System message should still be present (not injected)
        assert any(msg["role"] == "system" for msg in result)
        assert not any("<system_context>" in str(msg.get("content", "")) for msg in result)

class TestToolCallParsing:
    def test_parse_single_tool_call(self):
        """Should parse single tool call from Outlier response"""
        response = '''Let me read that file.
<invoke name="readFile"><parameter name="path">/test/file.js</parameter></invoke>
'''
        clean, calls = wormhole_oai.parse_all_tool_calls(response)

        assert len(calls) == 1
        assert calls[0]["type"] == "function"
        assert calls[0]["function"]["name"] == "readFile"
        args = json.loads(calls[0]["function"]["arguments"])
        assert args["path"] == "/test/file.js"
        assert "readFile" not in clean  # Should be removed from text

    def test_parse_multiple_tool_calls(self):
        """Should parse multiple tool calls"""
        response = '''
<invoke name="readFile"><parameter name="path">a.js</parameter></invoke>
<invoke name="readFile"><parameter name="path">b.js</parameter></invoke>
'''
        clean, calls = wormhole_oai.parse_all_tool_calls(response)

        assert len(calls) == 2
        assert calls[0]["function"]["name"] == "readFile"
        assert calls[1]["function"]["name"] == "readFile"

    def test_ignore_final_answer(self):
        """Should NOT parse final_answer as tool call"""
        response = '''
<invoke name="final_answer"><parameter name="answer">Done!</parameter></invoke>
'''
        clean, calls = wormhole_oai.parse_all_tool_calls(response)

        assert len(calls) == 0  # final_answer ignored
        assert "Done!" in clean  # Content preserved

class TestSSEFormatting:
    @pytest.mark.asyncio
    async def test_sse_stream_with_tool_calls(self):
        """Verify SSE stream format matches OpenAI spec"""
        # Mock data
        tool_calls = [{
            "id": "call_abc123",
            "type": "function",
            "function": {"name": "readFile", "arguments": '{"path":"test.js"}'}
        }]

        # Collect stream chunks
        chunks = []
        async for chunk in generate_sse_stream(tool_calls=tool_calls):
            chunks.append(json.loads(chunk.replace("data: ", "")))

        # Verify sequence
        assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        assert "beginToolCalls" in chunks[1]["choices"][0]["delta"]
        assert "tool_calls" in chunks[2]["choices"][0]["delta"]
        assert chunks[-2]["choices"][0]["finish_reason"] == "tool_calls"
        assert chunks[-1] == "[DONE]"
```

**Run Tests**: `pytest tests/unit/ -v --cov=services/oai`

### 8.2 Integration Tests

**Test File**: `tests/integration/test_vscode_integration.py`

```python
import pytest
import httpx
import asyncio

BASE_URL = "http://localhost:11434"
API_KEY = "test-key"

class TestVSCodeCompatibility:
    @pytest.mark.asyncio
    async def test_simple_text_request(self):
        """Test simple text-only request"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": "You are helpful"},
                        {"role": "user", "content": "Say hello"}
                    ],
                    "stream": False
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert "choices" in data
            assert data["choices"][0]["message"]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_tool_call_streaming(self):
        """Test tool call with streaming"""
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "Read test.js"}],
                    "tools": [{
                        "type": "function",
                        "function": {
                            "name": "readFile",
                            "parameters": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"]
                            }
                        }
                    }],
                    "stream": True
                }
            ) as response:
                chunks = []
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        chunks.append(line)

                # Verify proper SSE format
                assert any("beginToolCalls" in chunk for chunk in chunks)
                assert any("tool_calls" in chunk for chunk in chunks)
                assert chunks[-1] == "data: [DONE]"

    @pytest.mark.asyncio
    async def test_tool_result_handling(self):
        """Test full tool execution cycle"""
        # Step 1: Initial request
        response1 = await send_request({
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Read test.js"}],
            "tools": [readFile_tool],
            "stream": False
        })

        tool_calls = response1["choices"][0]["message"]["tool_calls"]
        assert len(tool_calls) > 0

        # Step 2: Send tool result
        response2 = await send_request({
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "Read test.js"},
                {"role": "assistant", "content": None, "tool_calls": tool_calls},
                {"role": "tool", "tool_call_id": tool_calls[0]["id"],
                 "name": "readFile", "content": "function test() {}"}
            ],
            "stream": False
        })

        # Should get final answer
        final_msg = response2["choices"][0]["message"]["content"]
        assert final_msg is not None
        assert len(final_msg) > 0
```

**Run Tests**: `pytest tests/integration/ -v -s`

### 8.3 Manual Testing with VSCode

**Setup VSCode**:

1. Install Continue or Copilot extension
2. Configure custom OpenAI endpoint:
   ```json
   {
     "models": [
       {
         "provider": "openai",
         "model": "gpt-4o",
         "apiBase": "http://localhost:11434/v1",
         "apiKey": "your-key"
       }
     ]
   }
   ```

**Manual Test Scenarios**:

| #   | Scenario          | Expected Behavior        | Pass/Fail |
| --- | ----------------- | ------------------------ | --------- |
| 1   | Simple question   | Text response, no tools  | [ ]       |
| 2   | "Read file X"     | Tool call for readFile   | [ ]       |
| 3   | "Create file Y"   | Tool call for createFile | [ ]       |
| 4   | "Read A and B"    | Multiple tool calls      | [ ]       |
| 5   | Execute tool      | Final answer after tool  | [ ]       |
| 6   | Error case        | Graceful error handling  | [ ]       |
| 7   | Long conversation | Context maintained       | [ ]       |
| 8   | New conversation  | System prompt injected   | [ ]       |

### 8.4 Performance Benchmarks

**Latency Targets**:

- Simple text request: < 2s response time
- Tool call request: < 3s to first tool call
- Tool result processing: < 2s to final answer
- Streaming TTFB: < 500ms

**Load Testing**:

```python
import asyncio
import aiohttp
import time

async def benchmark(num_requests=100):
    results = []
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i in range(num_requests):
            tasks.append(send_request(session))

        start = time.time()
        responses = await asyncio.gather(*tasks)
        duration = time.time() - start

    print(f"Completed {num_requests} requests in {duration:.2f}s")
    print(f"Avg: {duration/num_requests:.2f}s per request")
    print(f"RPS: {num_requests/duration:.2f}")
```

### 8.5 Regression Testing

Ensure existing functionality still works:

- [ ] Ollama-compatible endpoints (`/api/show`, `/chat/completions`)
- [ ] Authentication & authorization
- [ ] Model listing (`/v1/models`)
- [ ] Non-streaming responses
- [ ] Error responses (401, 403, 500)
- [ ] Conversation logging to data folder

---

## 9. Risk Assessment {#risk-assessment}

### 9.1 High Risk Items

#### Risk 1: System Prompt Injection Detection

**Description**: VSCode or users might notice system content in user messages  
**Likelihood**: Low  
**Impact**: Medium  
**Mitigation**:

- Use XML tags matching VSCode's existing pattern
- Only inject on NEW conversations
- Clear documentation in logs
- Feature flag for quick disable

#### Risk 2: SSE Format Incompatibility

**Description**: VSCode might not parse our SSE format correctly  
**Likelihood**: Medium  
**Impact**: High  
**Mitigation**:

- Strict adherence to OpenAI spec
- Extensive testing with real VSCode client
- Incremental rollout (test with single user first)
- Detailed logging of all SSE events
- Rollback plan ready

#### Risk 3: Tool Call Argument Parsing

**Description**: Complex or nested arguments might not parse correctly  
**Likelihood**: Medium  
**Impact**: Medium  
**Mitigation**:

- Comprehensive unit tests for edge cases
- Validation of JSON before sending
- Error handling for malformed arguments
- Fallback to text response on parse errors

### 9.2 Medium Risk Items

#### Risk 4: Performance Degradation

**Description**: Additional processing might slow down responses  
**Likelihood**: Low  
**Impact**: Medium  
**Mitigation**:

- Performance benchmarks before and after
- Optimize prompt injection (cache templates)
- Profile hot paths
- Monitor latency in production

#### Risk 5: Outlier Platform Changes

**Description**: Outlier might start honoring system prompts or change behavior  
**Likelihood**: Low  
**Impact**: Low  
**Mitigation**:

- Monitor Outlier release notes
- Test regularly with their platform
- Keep injection as toggle-able feature
- Maintain both code paths

#### Risk 6: Conversation State Leakage

**Description**: Global conversation ID might cause conflicts with multiple users  
**Likelihood**: Medium (if multi-user)  
**Impact**: High  
**Mitigation**:

- Document current single-user limitation
- Plan for user-session-based conversation tracking
- Add warning if concurrent requests detected
- Future: Implement proper session management

### 9.3 Low Risk Items

#### Risk 7: Tool Call ID Format

**Description**: Our generated IDs might not match expected format  
**Likelihood**: Low  
**Impact**: Low  
**Mitigation**: Use OpenAI's format (`call_` + 24 hex chars)

#### Risk 8: Logging Overhead

**Description**: Excessive logging might impact performance  
**Likelihood**: Low  
**Impact**: Low  
**Mitigation**: Use log levels, disable verbose logs in production

#### Risk 9: Template Loading Failures

**Description**: YAML templates might fail to load  
**Likelihood**: Very Low  
**Impact**: Medium  
**Mitigation**: Add existence checks, fallback templates, startup validation

### 9.4 Risk Response Plan

**If Critical Issue Detected**:

1. **Immediate**: Stop accepting new requests (return 503)
2. **Within 5 minutes**: Execute rollback (git revert + redeploy)
3. **Within 15 minutes**: Verify rollback successful, service restored
4. **Within 1 hour**: Root cause analysis, document issue
5. **Within 24 hours**: Fix implemented and tested, ready for re-deployment

**Monitoring Alerts**:

- Error rate > 5% → Alert immediately
- Avg latency > 5s → Alert within 5 minutes
- No requests for 10 minutes → Alert (service might be down)
- Tool call failure rate > 20% → Alert within 15 minutes

### 9.5 Success Criteria

**Deployment is considered successful when**:

- [ ] All unit tests passing (100% pass rate)
- [ ] All integration tests passing (100% pass rate)
- [ ] Manual testing checklist complete (100%)
- [ ] VSCode Copilot can connect and chat
- [ ] Tool calls work in VSCode UI
- [ ] Multi-turn conversations maintain context
- [ ] Error rate < 1% over 24 hours
- [ ] Latency within 10% of baseline
- [ ] No critical bugs reported
- [ ] Documentation complete and reviewed

**Definition of Done**:

1. Code merged to main branch
2. All tests green in CI/CD
3. Deployed to production
4. Monitored for 48 hours without issues
5. User acceptance testing complete
6. Documentation updated
7. Retrospective completed

---

## Document Status

- [x] Architecture Analysis completed
- [ ] Gap Analysis completed (Section marked as "TO BE FILLED BY SUBAGENT")
- [x] Prompt Injection Strategy designed
- [x] Tool Calling Format designed
- [x] Tool Result Handling designed
- [x] Implementation Steps detailed
- [x] Testing Strategy completed
- [x] Risk Assessment completed
- [x] Final review completed
