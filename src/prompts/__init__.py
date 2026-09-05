from pathlib import Path

from jinja2 import FileSystemLoader, Environment, Template


def get_prompt_template(prompt_file_name: str) -> Template:
    curr_dir = Path(__file__).parent
    env = Environment(loader=FileSystemLoader(curr_dir))
    return env.get_template(prompt_file_name)


