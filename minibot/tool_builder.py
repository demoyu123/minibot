from __future__ import annotations

import re
from pathlib import Path


CUSTOM_TOOLS_PATH = Path("minibot/custom_tools.py")


def normalize_tool_name(name: str) -> str:
    clean = re.sub(r"\W+", "_", name.strip().lower())
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        clean = "custom_tool"
    if clean[0].isdigit():
        clean = "tool_" + clean
    return clean


def scaffold_http_tool(name: str, path: Path = CUSTOM_TOOLS_PATH) -> str:
    tool_name = normalize_tool_name(name)
    env_name = "MINIBOT_TOOL_" + tool_name.upper() + "_URL"
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(_header(), encoding="utf-8")

    text = path.read_text(encoding="utf-8")
    if f'name="{tool_name}"' in text:
        return tool_name

    with path.open("a", encoding="utf-8") as f:
        f.write(_tool_block(tool_name, env_name))
    return tool_name


def _header() -> str:
    return '''"""User-created minibot tools.

Each tool is intentionally small. Edit this file when you want a custom tool
to fetch real data from an API or local system.
"""

from __future__ import annotations

import os
import urllib.parse
import urllib.request

from minibot.tools import Tool


def _http_get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")[:4000]


def register(registry):
    """Called by minibot at startup to register custom tools."""
'''


def _tool_block(tool_name: str, env_name: str) -> str:
    return f'''

    def {tool_name}(query: str) -> str:
        """Fetch real data for {tool_name}.

        Configure the API endpoint with:
            {env_name}

        The URL may contain {{query}}, for example:
            https://api.example.com/search?q={{query}}
        """
        url_template = os.getenv("{env_name}", "")
        if not url_template:
            return (
                "Tool `{tool_name}` has been created, but no real data source is configured yet. "
                "Set environment variable {env_name} to an HTTP API URL. "
                "Use {{query}} in the URL where the user query should be inserted."
            )
        url = url_template.format(query=urllib.parse.quote(query))
        return _http_get(url)

    registry.add(Tool(
        name="{tool_name}",
        description="User-created HTTP data tool. Input is a natural-language query.",
        parameters={{"query": "str"}},
        func={tool_name},
    ))
'''
