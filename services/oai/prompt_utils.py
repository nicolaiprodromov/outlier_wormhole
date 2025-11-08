from jinja2 import Template, StrictUndefined

def populate_template(template: str, variables: dict) -> str:
    compiled_template = Template(template, undefined=StrictUndefined)
    try:
        return compiled_template.render(**variables)
    except Exception as e:
        raise Exception(f"Error during jinja template rendering: {type(e).__name__}: {e}")

def to_tool_calling_prompt(tool: dict) -> str:
    function = tool.get("function", {})
    name = function.get("name", "unknown")
    description = function.get("description", "")
    
    desc_short = description[:80] + "..." if len(description) > 80 else description
    
    return f"- {name}: {desc_short}"

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
