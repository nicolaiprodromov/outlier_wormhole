from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import time
import uuid
import os
import re
from pathlib import Path
from template_composer import TemplateComposer
from dump_raw import dump_raw_prompts
from agent_workflow import AgentWorkflow

app = FastAPI()


@app.middleware("http")
async def accept_authorization_header(request: Request, call_next):
    auth_header = request.headers.get("authorization", "None")
    print(
        f"[Request] {request.method} {request.url.path} | Auth: {auth_header[:50] if auth_header != 'None' else 'None'}..."
    )
    response = await call_next(request)
    print(f"[Response] Status: {response.status_code}")
    return response


active_conversation_id = None
composer = TemplateComposer()
DATA_FOLDER = Path("data")
DATA_FOLDER.mkdir(exist_ok=True)
conversation_logs = {}
agent_workflow = AgentWorkflow(
    lambda: active_conversation_id,
    lambda cid: set_active_conversation(cid),
    lambda cid, p, s, r: log_to_data_folder(cid, p, s, r),
)


def set_active_conversation(conversation_id):
    global active_conversation_id
    active_conversation_id = conversation_id


def log_to_data_folder(conversation_id, prompt, system_message, response):
    timestamp = int(time.time())
    if conversation_id not in conversation_logs:
        conversation_logs[conversation_id] = []
    log_entry = {
        "timestamp": timestamp,
        "index": len(conversation_logs[conversation_id]),
    }
    conversation_logs[conversation_id].append(log_entry)
    conv_folder = DATA_FOLDER / conversation_id
    conv_folder.mkdir(exist_ok=True)
    index = log_entry["index"]
    (conv_folder / f"{index}_system.md").write_text(system_message, encoding="utf-8")
    (conv_folder / f"{index}_prompt.md").write_text(prompt, encoding="utf-8")
    (conv_folder / f"{index}_response.md").write_text(response, encoding="utf-8")


@app.get("/api/version")
async def api_version():
    return {"version": "1.0.0"}


@app.post("/api/show")
async def ollama_show(request: Request):
    body = await request.json()
    model_name = body.get("name", "")
    print(f"Received /api/show request for model: {model_name}")
    return {
        "modelfile": f"# Modelfile for {model_name}",
        "parameters": "",
        "template": "",
        "details": {
            "format": "gguf",
            "family": "llama",
            "families": ["llama"],
            "parameter_size": "8B",
            "quantization_level": "Q4_0",
        },
    }


@app.post("/chat/completions")
async def ollama_chat(request: Request):
    return await chat_completions(request)


@app.get("/v1/models")
async def list_models():
    print(f"Received /v1/models request")
    return {
        "object": "list",
        "data": [
            {
                "id": "gpt-5-chat",
                "object": "model",
                "created": 1730419200,
                "owned_by": "openai",
            },
            {
                "id": "gpt-5-2025-08-07",
                "object": "model",
                "created": 1730419200,
                "owned_by": "openai",
            },
            {
                "id": "GPT-4o",
                "object": "model",
                "created": 1715367600,
                "owned_by": "openai",
            },
            {
                "id": "gpt-4o-audio-preview-2025-06-03",
                "object": "model",
                "created": 1730419200,
                "owned_by": "openai",
            },
            {
                "id": "gpt-4o-mini-audio-preview-2024-12-17",
                "object": "model",
                "created": 1730419200,
                "owned_by": "openai",
            },
            {
                "id": "GPT-4.1",
                "object": "model",
                "created": 1715367600,
                "owned_by": "openai",
            },
            {
                "id": "o3",
                "object": "model",
                "created": 1730419200,
                "owned_by": "openai",
            },
            {
                "id": "o4-mini",
                "object": "model",
                "created": 1730419200,
                "owned_by": "openai",
            },
            {
                "id": "claude-sonnet-4-5-20250929",
                "object": "model",
                "created": 1730419200,
                "owned_by": "anthropic",
            },
            {
                "id": "claude-haiku-4-5-20251001",
                "object": "model",
                "created": 1730419200,
                "owned_by": "anthropic",
            },
            {
                "id": "claude-opus-4-1-20250805",
                "object": "model",
                "created": 1730419200,
                "owned_by": "anthropic",
            },
            {
                "id": "claude-opus-4-20250514",
                "object": "model",
                "created": 1730419200,
                "owned_by": "anthropic",
            },
            {
                "id": "claude-sonnet-4-20250514",
                "object": "model",
                "created": 1730419200,
                "owned_by": "anthropic",
            },
            {
                "id": "gemini-2.5-pro-preview-06-05",
                "object": "model",
                "created": 1730419200,
                "owned_by": "google",
            },
            {
                "id": "gemini-2.5-flash-preview-05-20",
                "object": "model",
                "created": 1730419200,
                "owned_by": "google",
            },
            {
                "id": "Grok 3",
                "object": "model",
                "created": 1730419200,
                "owned_by": "xai",
            },
            {
                "id": "Llama 4 Maverick",
                "object": "model",
                "created": 1730419200,
                "owned_by": "meta",
            },
            {
                "id": "qwen3-235b-a22b-2507-v1",
                "object": "model",
                "created": 1730419200,
                "owned_by": "alibaba",
            },
            {
                "id": "deepseek-r1-0528",
                "object": "model",
                "created": 1730419200,
                "owned_by": "deepseek",
            },
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    print(f"Received /v1/chat/completions request")
    print(f"Model: {body.get('model')}")
    print(f"Stream: {body.get('stream')}")
    print(f"Tools: {len(body.get('tools', []))} tools")
    model = body.get("model")

    if not model:
        return {
            "error": {
                "message": "Model is required",
                "type": "invalid_request_error",
                "code": "model_required",
            }
        }, 400

    messages = body.get("messages", [])
    stream = body.get("stream", False)
    tools = body.get("tools", [])
    tool_choice = body.get("tool_choice", "auto")

    print(f"Message roles in request: {[msg.get('role') for msg in messages]}")

    raw_system = ""
    raw_user = ""
    user_request = ""
    attachments = ""
    has_tool_results = False
    last_assistant_had_final_answer = False

    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "system":
            raw_system = content

        elif role == "user":
            if isinstance(content, str):
                raw_user = content
            elif isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                raw_user = " ".join(text_parts) if text_parts else str(content)
            else:
                raw_user = str(content)
            attachments_match = re.search(
                r"<attachments>(.*?)</attachments>", raw_user, re.DOTALL
            )
            if attachments_match:
                attachments = attachments_match.group(0)
            user_request_match = re.search(
                r"<userRequest>(.*?)</userRequest>", raw_user, re.DOTALL
            )
            if user_request_match:
                user_request = user_request_match.group(1).strip()
            else:
                user_request = raw_user
            has_tool_results = False

        elif role == "assistant":
            assistant_content = msg.get("content", "")
            if assistant_content and agent_workflow.has_final_answer_marker(
                assistant_content
            ):
                last_assistant_had_final_answer = True
            else:
                last_assistant_had_final_answer = False

        elif role == "tool":
            has_tool_results = True

    if raw_system or raw_user:
        dump_raw_prompts(raw_system, raw_user)
        print(
            f"aved raw prompts - system: {len(raw_system)} chars, user: {len(raw_user)} chars"
        )
    else:
        print(f"No system/user messages to dump")

    has_assistant_messages = any(msg.get("role") == "assistant" for msg in messages)
    is_new_conversation = not has_assistant_messages

    if is_new_conversation:
        global active_conversation_id
        active_conversation_id = None
        print(
            f"New conversation detected (no assistant messages, total messages: {len(messages)})"
        )
    else:
        print(
            f"Continuing conversation (has assistant messages, total messages: {len(messages)})"
        )

    if tools and (not has_tool_results or last_assistant_had_final_answer):
        clean_text, tool_calls, conversation_id = (
            await agent_workflow.handle_initial_tool_request(
                model, user_request, tools, attachments, raw_system
            )
        )
        if conversation_id is None:
            return {
                "error": {
                    "message": "Failed to create conversation",
                    "type": "server_error",
                }
            }, 500
    else:
        if has_tool_results and not last_assistant_had_final_answer:
            clean_text, tool_calls, conversation_id = (
                await agent_workflow.handle_tool_response(model, messages, raw_system)
            )
            if conversation_id is None:
                return {
                    "error": {
                        "message": "Failed to create conversation",
                        "type": "server_error",
                    }
                }, 500
        else:
            clean_text, tool_calls, conversation_id = (
                await agent_workflow.handle_simple_user_message(
                    model, user_request, attachments, raw_system
                )
            )
            if conversation_id is None:
                return {
                    "error": {
                        "message": "Failed to get response from Outlier",
                        "type": "server_error",
                    }
                }, 500

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
    created_time = int(time.time())

    if stream:

        async def generate():
            chunk_id = completion_id
            first_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "system_fingerprint": None,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "logprobs": None,
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(first_chunk)}\n\n"
            if tool_calls:
                for tool_call in tool_calls:
                    tool_chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model,
                        "system_fingerprint": None,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"tool_calls": [tool_call]},
                                "logprobs": None,
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(tool_chunk)}\n\n"
            elif clean_text:
                lines = clean_text.split("\n")
                for line_idx, line in enumerate(lines):
                    if line_idx > 0:
                        newline_chunk = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model,
                            "system_fingerprint": None,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": "\n"},
                                    "logprobs": None,
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(newline_chunk)}\n\n"
                    if line.strip():
                        words = line.split()
                        for i, word in enumerate(words):
                            word_with_space = (
                                word if i == len(words) - 1 else word + " "
                            )
                            chunk = {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": model,
                                "system_fingerprint": None,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": word_with_space},
                                        "logprobs": None,
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"
            final_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": model,
                "system_fingerprint": None,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "logprobs": None,
                        "finish_reason": "tool_calls" if tool_calls else "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        prompt_tokens = sum(
            len(msg.get("content", "").split())
            for msg in messages
            if msg.get("content")
        )
        completion_tokens = len(clean_text.split()) if clean_text else 0
        if tool_calls:
            message_content = {
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls,
            }
        else:
            message_content = {"role": "assistant", "content": clean_text or ""}
        response = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created_time,
            "model": model,
            "system_fingerprint": None,
            "choices": [
                {
                    "index": 0,
                    "message": message_content,
                    "logprobs": None,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        return response


if __name__ == "__main__":
    import uvicorn
    import os

    host = os.getenv("oai_host", "0.0.0.0")
    port = int(os.getenv("oai_port", "11434"))
    print("URL: {}://{}:{}".format("http", host, port))
    print("Available endpoints:")
    print("   ├─ OpenAI-compatible:")
    print("   │    ├─ GET  /v1/models")
    print("   │    └─ POST /v1/chat/completions")
    print("   └─ Ollama-compatible:")
    print("        ├─ POST /api/show")
    print("        └─ POST /chat/completions")
    print("Available models:")
    print("   ├─ GPT-5, GPT-4o, GPT-4.1, o3, o4-mini")
    print("   ├─ Claude Sonnet/Opus/Haiku 4.x series")
    print("   ├─ Gemini 2.5 Pro/Flash")
    print("   ├─ Grok 3, Llama 4 Maverick")
    print("   └─ Qwen3, DeepSeek-R1")
    uvicorn.run(
        app,
        host=host,
        port=port,
    )
