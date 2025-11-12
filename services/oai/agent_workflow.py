import re
import json
import uuid
from pathlib import Path
from send import send_script_async
from template_composer import TemplateComposer
from prompt_utils import (
    to_tool_calling_prompt,
    extract_client_instructions,
    extract_context_tag,
)


class AgentWorkflow:
    def __init__(
        self, get_conversation_callback, set_conversation_callback, log_callback
    ):
        print("[Agent] Initializing with smolagents pattern")
        self.get_conversation_id = get_conversation_callback
        self.set_conversation_id = set_conversation_callback
        self.log_callback = log_callback
        self.composer = TemplateComposer()
        self.max_steps = 20
        self.step_number = 0

    async def get_or_create_conversation(
        self, model, first_prompt=None, first_system=None
    ):
        conversation_id = self.get_conversation_id()

        if conversation_id:
            print(f"[Agent Workflow] Using existing conversation: {conversation_id}")
            return conversation_id, None

        input_data = {
            "prompt": first_prompt or "Hello",
            "model": model,
            "systemMessage": first_system or "",
        }

        print(f"[Agent Workflow] Creating new conversation for model: {model}")
        result = await send_script_async("create_conversation.js", input_data)
        print(f"[Agent Workflow] Create conversation result: {result}")

        if result.get("success"):
            parsed_result = result.get("result")
            if isinstance(parsed_result, str):
                try:
                    parsed_result = json.loads(parsed_result)
                except:
                    pass

            if (
                parsed_result
                and isinstance(parsed_result, dict)
                and parsed_result.get("conversationId")
            ):
                conversation_id = parsed_result["conversationId"]
                self.set_conversation_id(conversation_id)
                print(f"[Agent] Created and cached conversation ID: {conversation_id}")
                return conversation_id, parsed_result.get("response")

        print(f"[Agent Workflow] Failed to create conversation: {result}")
        return None, None

    async def send_to_outlier(
        self,
        conversation_id,
        prompt,
        model,
        system_message="",
    ):
        input_data = {
            "conversationId": conversation_id,
            "prompt": prompt,
            "model": model,
            "systemMessage": system_message,
        }

        print(f"[Agent] Sending prompt ({len(prompt)} chars) to Outlier")
        result = await send_script_async("send_message.js", input_data)

        if result.get("success"):
            parsed_result = result.get("result")
            if isinstance(parsed_result, str):
                try:
                    parsed_result = json.loads(parsed_result)
                except:
                    pass

            if parsed_result and isinstance(parsed_result, dict):
                response = parsed_result.get("response", "")
                print(f"[Agent] Got response ({len(response)} chars) from Outlier")

                self.log_callback(conversation_id, prompt, system_message, response)

                return response, parsed_result

        print(f"[Agent] Failed: {result} sending prompt to Outlier")
        return None, None

    def parse_tool_call(self, response_text):
        invoke_pattern = r'<invoke name="([^"]+)">(.*?)</invoke>'
        match = re.search(invoke_pattern, response_text, re.DOTALL)

        if not match:
            return None, None

        tool_name, params_block = match.groups()
        param_pattern = r'<parameter name="([^"]+)">(.*?)</parameter>'
        params = re.findall(param_pattern, params_block, re.DOTALL)

        arguments = {param_name: param_value for param_name, param_value in params}

        tool_call = {
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(arguments)},
        }

        print(f"[Agent] Parsed tool call: {tool_name}")

        remaining_text = response_text[: match.start()] + response_text[match.end() :]
        return remaining_text, tool_call

    def extract_final_answer(self, response_text):
        invoke_final_pattern = r'<invoke name="final_answer">\s*<parameter name="answer">(.*?)</parameter>\s*</invoke>'
        match = re.search(invoke_final_pattern, response_text, re.DOTALL)
        if match:
            return match.group(1)

        final_answer_pattern = r"<final_answer>(.*?)</final_answer>"
        match = re.search(
            final_answer_pattern, response_text, re.DOTALL | re.IGNORECASE
        )
        if match:
            return match.group(1)

        cleaned = re.sub(
            r"<final_answer>|</final_answer>|\[FINAL ANSWER\]|FINAL:",
            "",
            response_text,
            flags=re.IGNORECASE,
        )
        return cleaned

    def has_final_answer_marker(self, response_text):
        return (
            'name="final_answer"' in response_text
            or "<final_answer>" in response_text.lower()
        )

    def initialize_system_prompt(
        self,
        tools,
        user_request,
        attachments="",
        context="",
        custom_instructions="",
        is_first=False,
    ):
        rules_path = Path("templates/rules.mdx")
        rules_content = (
            rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
        )

        return self.composer.initialize_system_prompt(
            tools=tools,
            managed_agents=None,
            custom_instructions=custom_instructions,
            rules=rules_content,
            attachments=attachments,
            context=context,
            user_request=user_request,
            is_first=is_first,
        )

    async def step(self, conversation_id, model):
        self.step_number += 1

        if self.step_number >= self.max_steps:
            print(f"[Agent] Max steps ({self.max_steps}) reached")
            return "Maximum steps reached. Task could not be completed.", None, True

        return None, None, False

    async def execute_agent_loop(
        self,
        conversation_id,
        user_request,
        model,
        tools,
        attachments="",
        context="",
        custom_instructions="",
        is_first=False,
    ):

        prompt = self.initialize_system_prompt(
            tools, user_request, attachments, context, custom_instructions, is_first
        )

        system_message = self.composer.get_system()

        response_text, _ = await self.send_to_outlier(
            conversation_id, prompt, model, system_message
        )

        if response_text is None:
            return "Error: Failed to get response from model", None

        print(f"[Agent Loop] Raw response: {response_text[:100]}...")

        if self.has_final_answer_marker(response_text):
            final_text = self.extract_final_answer(response_text)
            print(f"[Agent Loop] Final answer detected: {final_text[:100]}...")
            return final_text, None

        clean_text, tool_call = self.parse_tool_call(response_text)

        if tool_call:
            print(f"[Agent Loop] Tool call detected: {tool_call['function']['name']}")
            return clean_text, [tool_call]
        else:
            print(f"[Agent Loop] No tool call or final answer detected")
            return response_text, None

    async def handle_initial_tool_request(
        self,
        model,
        user_request,
        tools,
        attachments,
        context,
        raw_system,
        is_first=False,
    ):
        print(
            f"[Agent] handle_initial_tool_request: model={model}, tools={len(tools)}, is_first={is_first}"
        )

        custom_instructions = extract_client_instructions(raw_system)
        if custom_instructions:
            print(
                f"[Agent] Extracted custom instructions: {len(custom_instructions)} chars"
            )

        if context:
            print(f"[Agent] Received context: {len(context)} chars")

        prompt = self.initialize_system_prompt(
            tools,
            user_request,
            attachments,
            context,
            custom_instructions,
            is_first=is_first,
        )

        system_message = self.composer.get_system()

        conversation_id, first_response = await self.get_or_create_conversation(
            model, prompt, system_message
        )

        if not conversation_id:
            print("[Agent] Failed to get or create conversation")
            return None, None, None

        if first_response:
            self.log_callback(
                conversation_id,
                prompt,
                system_message,
                first_response,
            )
            if self.has_final_answer_marker(first_response):
                clean_text = self.extract_final_answer(first_response)
                tool_calls = None
            else:
                clean_text, tool_call = self.parse_tool_call(first_response)
                tool_calls = [tool_call] if tool_call else None
                if not clean_text and not tool_call:
                    clean_text = first_response
        else:
            clean_text, tool_calls = await self.execute_agent_loop(
                conversation_id,
                user_request,
                model,
                tools,
                attachments,
                context,
                custom_instructions,
                is_first=is_first,
            )

        print(
            f"[Agent] Returning: text={bool(clean_text)}, tools={len(tool_calls) if tool_calls else 0}"
        )
        return clean_text, tool_calls, conversation_id

    async def handle_tool_response(self, model, messages, raw_system):
        print(f"[Agent] handle_tool_response: model={model}, messages={len(messages)}")

        context = extract_context_tag(raw_system)
        if context:
            print(f"[Agent] Extracted context for tool response: {len(context)} chars")

        tool_output_parts = []
        last_assistant_msg = None

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
        prompt = self.composer.compose_tool_response(tool_output, context)

        system_message = self.composer.get_system()

        conversation_id, _ = await self.get_or_create_conversation(
            model, prompt, system_message
        )
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

        print(
            f"[Agent] Returning: text={bool(clean_text)}, tools={len(tool_calls) if tool_calls else 0}"
        )
        return clean_text, tool_calls, conversation_id

    async def handle_simple_user_message(
        self, model, user_request, attachments, raw_system, is_first=False
    ):
        print(f"[Agent Workflow] handling user message to {model}, is_first={is_first}")

        system_content = self.composer.get_system()

        context = extract_context_tag(raw_system)
        if context:
            print(f"[Agent] Extracted context: {len(context)} chars")

        prompt = self.composer.compose_simple_user(
            system=system_content,
            attachments=attachments,
            context=context,
            user_request=user_request,
            is_first=is_first,
        )

        system_message = self.composer.get_system()

        conversation_id, first_response = await self.get_or_create_conversation(
            model, prompt, system_message
        )
        if not conversation_id:
            print("[Agent Workflow] Failed to get or create conversation")
            return None, None, None

        if first_response:
            self.log_callback(conversation_id, prompt, system_message, first_response)
            clean_text = first_response
            tool_calls = None
        else:
            response_text, _ = await self.send_to_outlier(
                conversation_id, prompt, model, system_message
            )
            if response_text is None:
                print("[Agent Workflow] Failed to get response from Outlier")
                return None, None, None
            clean_text = response_text
            tool_calls = None

        return clean_text, tool_calls, conversation_id
