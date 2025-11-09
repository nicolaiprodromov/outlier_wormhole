import yaml
from pathlib import Path
from prompt_utils import populate_template, to_tool_calling_prompt, to_code_prompt


class TemplateComposer:
    def __init__(
        self, templates_dir: str = "templates", prompts_file="agent_prompts.yaml"
    ):
        self.templates_dir = Path(templates_dir)
        self.prompts_file = Path(prompts_file)
        self._system_cache = None
        self.prompt_templates = self._load_prompts()

    def _load_prompts(self):
        if self.prompts_file.exists():
            with open(self.prompts_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return {}

    def get_system(self):
        if self._system_cache is None:
            system_path = self.templates_dir / "system.mdx"
            if system_path.exists():
                self._system_cache = system_path.read_text(encoding="utf-8")
            else:
                self._system_cache = "You are a helpful assistant."
        return self._system_cache

    def initialize_system_prompt(
        self,
        tools=None,
        managed_agents=None,
        custom_instructions=None,
        rules=None,
        attachments=None,
        user_request=None,
    ):
        tools_list = []
        if tools:
            for tool in tools:
                tools_list.append(to_tool_calling_prompt(tool))
        variables = {
            "tools": tools_list,
            "managed_agents": managed_agents or [],
            "custom_instructions": custom_instructions or "",
            "rules": rules or "",
            "attachments": attachments or "",
            "user_request": user_request or "",
        }
        system_prompt_template = self.prompt_templates.get("system_prompt", "")
        return populate_template(system_prompt_template, variables)

    def compose_tool_response(self, tool_output):
        template = self.prompt_templates.get("tool_response", "{{tool_output}}")
        return populate_template(template, {"tool_output": tool_output})

    def compose_simple_user(self, system=None, attachments=None, user_request=None):
        template = self.prompt_templates.get("simple_user", "{{user_request}}")
        variables = {
            "system": system or "",
            "attachments": attachments or "",
            "user_request": user_request or "",
        }
        return populate_template(template, variables)

    def compose(self, template_name: str, **variables):
        template_path = self.templates_dir / f"{template_name}.mdx"
        if template_path.exists():
            template_content = template_path.read_text(encoding="utf-8")
            result = template_content
            for key, value in variables.items():
                placeholder = f"{{{{{key}}}}}"
                result = result.replace(placeholder, str(value) if value else "")
            import re

            for remaining_key in re.findall(r"\{\{(\w+)\}\}", result):
                result = result.replace(f"{{{{{remaining_key}}}}}", "")
            return result
        if template_name in self.prompt_templates:
            return populate_template(self.prompt_templates[template_name], variables)
        raise ValueError(f"Template not found: {template_name}")
