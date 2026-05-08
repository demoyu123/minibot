from __future__ import annotations

import ast
import importlib.util
import json
import operator as op
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from minibot.memory import Memory
from minibot.rag import SimpleRAG


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, str]
    func: Callable[..., str]

    def run(self, args: dict[str, Any]) -> str:
        return self.func(**args)


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None):
        self.tools = {t.name: t for t in tools or []}
        self.last_missing_tool = ""

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def run(self, name: str, args: dict[str, Any]) -> str:
        if name not in self.tools:
            self.last_missing_tool = name
            return (
                f"MISSING_TOOL: {name}\n"
                f"\u5f53\u524d\u53ef\u7528\u5de5\u5177: {', '.join(self.tools)}\n"
                "\u8fd9\u4e2a\u4efb\u52a1\u9700\u8981 minibot \u8fd8\u6ca1\u6709\u7684\u5de5\u5177\u3002"
            )
        try:
            return self.tools[name].run(args)
        except TypeError as e:
            return f"\u5de5\u5177 `{name}` \u7684\u53c2\u6570\u4e0d\u6b63\u786e\uff1a{e}"
        except Exception as e:
            return f"\u5de5\u5177 `{name}` \u8c03\u7528\u5931\u8d25\uff1a{type(e).__name__}: {e}"

    def prompt(self) -> str:
        lines = []
        for tool in self.tools.values():
            lines.append(f"- {tool.name}: {tool.description}; args={tool.parameters}")
        return "\n".join(lines)


def calculator(expression: str) -> str:
    allowed = {
        ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
        ast.Div: op.truediv, ast.Pow: op.pow, ast.USub: op.neg,
    }

    def eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
            return allowed[type(node.op)](eval_node(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            return allowed[type(node.op)](eval_node(node.left), eval_node(node.right))
        raise ValueError("only simple math is allowed")

    return str(eval_node(ast.parse(expression, mode="eval").body))


def get_weather(location: str = "", date: str = "today") -> str:
    """Fetch current or forecast weather from wttr.in without an API key."""
    url = "https://wttr.in/" + urllib.parse.quote(location) + "?format=j1"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    area = data.get("nearest_area", [{}])[0]
    place = area.get("areaName", [{"value": location}])[0]["value"]

    target = _weather_day_index(date)
    days = data.get("weather", [])
    if target > 0:
        if target >= len(days):
            return f"weather data for date={date} is not available."
        day = days[target]
        hourly = _representative_hour(day)
        return (
            f"time={datetime.now().isoformat(timespec='minutes')}\n"
            f"location={place}\n"
            f"date={day.get('date')}\n"
            f"weather={hourly.get('weatherDesc', [{'value': ''}])[0]['value']}\n"
            f"avg_temperature_c={day.get('avgtempC')}\n"
            f"min_temperature_c={day.get('mintempC')}\n"
            f"max_temperature_c={day.get('maxtempC')}\n"
            f"humidity={hourly.get('humidity')}%\n"
            f"wind_kmph={hourly.get('windspeedKmph')}"
        )

    now = data["current_condition"][0]
    today = days[0] if days else {}
    return (
        f"time={datetime.now().isoformat(timespec='minutes')}\n"
        f"location={place}\n"
        f"date={today.get('date', 'today')}\n"
        f"weather={now.get('weatherDesc', [{'value': ''}])[0]['value']}\n"
        f"temperature_c={now.get('temp_C')}\n"
        f"feels_like_c={now.get('FeelsLikeC')}\n"
        f"humidity={now.get('humidity')}%\n"
        f"wind_kmph={now.get('windspeedKmph')}"
    )


def _weather_day_index(date: str) -> int:
    normalized = str(date or "today").strip().lower()
    if normalized in {"tomorrow", "\u660e\u5929", "tmr", "next day", "+1", "1"}:
        return 1
    return 0


def _representative_hour(day: dict[str, Any]) -> dict[str, Any]:
    hours = day.get("hourly") or []
    if not hours:
        return {}
    return min(hours, key=lambda x: abs(int(x.get("time", "1200")) - 1200))


def default_tools(memory: Memory, rag: SimpleRAG | None = None) -> ToolRegistry:
    rag = rag or SimpleRAG()

    def remember(text: str) -> str:
        return memory.long.add(text)

    def search_memory(query: str) -> str:
        results = memory.long.search(query)
        return "\n".join(f"- {x}" for x in results) if results else "No memory found."

    def search_docs(query: str, limit: int = 3) -> str:
        chunks = rag.search(query, limit=limit)
        if not chunks:
            return "No related document chunks found."
        return "\n\n".join(f"[{c.source}]\n{c.text}" for c in chunks)

    registry = ToolRegistry([
        Tool("calculator", "Calculate a simple math expression.", {"expression": "str"}, calculator),
        Tool("get_weather", "Get current or tomorrow weather for a city. Use date='today' or date='tomorrow'.", {"location": "str", "date": "str"}, get_weather),
        Tool("remember", "Save an important durable fact to long-term memory.", {"text": "str"}, remember),
        Tool("search_memory", "Search long-term memory.", {"query": "str"}, search_memory),
        Tool("search_docs", "Retrieve local knowledge-base chunks from data/docs.", {"query": "str", "limit": "int"}, search_docs),
    ])
    load_custom_tools(registry)
    return registry


def load_custom_tools(registry: ToolRegistry, path: Path = Path("minibot/custom_tools.py")) -> None:
    if not path.exists():
        return
    spec = importlib.util.spec_from_file_location("minibot_custom_tools_runtime", path)
    if not spec or not spec.loader:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, "register", None)
    if callable(register):
        register(registry)
