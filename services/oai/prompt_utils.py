import re
from jinja2 import Template, StrictUndefined


def extract_client_instructions(raw_system: str) -> str:
    """
    Extract the last <instructions> tag from the raw system prompt.
    This contains client-specific instructions (like .github/instructions files)
    that should be preserved and passed through to the agent.

    The raw system prompt may contain multiple <instructions> tags:
    1. General instructions about the agent behavior (we discard this)
    2. Client-specific instructions at the end (we need to extract this)

    Returns the content of the last <instructions> tag, or empty string if not found.
    """
    if not raw_system:
        return ""

    # Find all <instructions> tags
    pattern = r"<instructions>(.*?)</instructions>"
    matches = list(re.finditer(pattern, raw_system, re.DOTALL))

    if not matches:
        return ""

    # Return the last <instructions> tag (the client-specific one)
    last_match = matches[-1]
    return last_match.group(0)


def extract_context_tag(raw_system: str) -> str:
    """
    Extract the <context> tag from the raw system prompt.
    This contains vital information like current date, OS, workspace structure, etc.
    that should be preserved and passed through to the agent.

    Returns the content of the <context> tag, or empty string if not found.
    """
    if not raw_system:
        return ""

    pattern = r"<context>(.*?)</context>"
    match = re.search(pattern, raw_system, re.DOTALL)

    if not match:
        return ""

    return match.group(0)


def populate_template(template: str, variables: dict) -> str:
    compiled_template = Template(template, undefined=StrictUndefined)
    try:
        return compiled_template.render(**variables)
    except Exception as e:
        raise Exception(
            f"Error during jinja template rendering: {type(e).__name__}: {e}"
        )


def to_tool_calling_prompt(tool: dict) -> str:
    function = tool.get("function", {})
    name = function.get("name", "unknown")
    description = function.get("description", "")
    return f"- {name}: {description}"


def to_simple_tool_prompt(tool: dict) -> str:
    function = tool.get("function", {})
    name = function.get("name", "unknown")
    parameters = function.get("parameters", {})
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])

    params = []
    for prop_name, prop_info in properties.items():
        prop_type = prop_info.get("type", "any")
        params.append(f"{prop_name}: {prop_type}")

    params_str = ", ".join(params) if params else ""
    return f"- {name}({params_str})"


def to_code_prompt(tool: dict) -> str:
    function = tool.get("function", {})
    name = function.get("name", "unknown")
    description = function.get("description", "")
    parameters = function.get("parameters", {})
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])
    args = []
    for prop_name, prop_info in properties.items():
        prop_type = prop_info.get("type", "Any")
        is_required = prop_name in required
        args.append(f"{prop_name}: {prop_type}")
    args_str = ", ".join(args)
    return f'''def {name}({args_str}) -> str:
    """{description}"""
    pass
'''
