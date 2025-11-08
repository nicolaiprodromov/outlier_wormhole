from pathlib import Path
from datetime import datetime
RAW_DUMPS_FOLDER = Path("data/raw_dumps")
RAW_DUMPS_FOLDER.mkdir(exist_ok=True)
def dump_raw_prompts(system_message: str, user_prompt: str):
    timestamp = int(datetime.now().timestamp())
    system_file = RAW_DUMPS_FOLDER / f"system_{timestamp}.md"
    user_file = RAW_DUMPS_FOLDER / f"user_{timestamp}.md"
    system_file.write_text(system_message, encoding="utf-8")
    user_file.write_text(user_prompt, encoding="utf-8")
    return timestamp
