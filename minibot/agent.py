from __future__ import annotations

import json
import re
import asyncio
from dataclasses import dataclass

from minibot.llm import LLM
from minibot.memory import Memory
from minibot.tools import Tool, ToolRegistry, default_tools


SYSTEM_PROMPT = """You are MiniBot, the user's dedicated personal intelligent agent.

Identity:
- You are built for this user as a personal agent, not a generic teaching assistant.
- Your job is to help with the user's daily tasks, learning, planning, coding, memory, and tool-based work.
- Be warm, concise, proactive, and practical.
- When asked who you are, introduce yourself as the user's dedicated personal intelligent agent.

Use this ReAct JSON protocol every turn:

To call a tool:
{"thought":"why this tool is needed","action":"tool_name","action_input":{"arg":"value"}}

To finish:
{"thought":"why the task is done","final":"answer to user"}

Rules:
- Output JSON only. No markdown fences.
- Use tools when calculation, weather lookup, memory lookup, memory writing, or document retrieval helps.
- For today's, tomorrow's, or current weather, call get_weather instead of guessing.
- When the user asks about tomorrow's weather, call get_weather with date="tomorrow".
- Use ask_subagent when a focused helper agent can solve a smaller subtask mid-turn.
- Use ask_subagents when several independent subtasks can be solved in parallel.
- If no available tool can fetch required real data, say what is missing instead of inventing facts.
- After an observation, either call another tool or produce final.
"""


@dataclass
class Step:
    thought: str
    action: str | None = None
    action_input: dict | None = None
    observation: str | None = None
    final: str | None = None


class MiniBot:
    def __init__(
        self,
        llm: LLM,
        memory: Memory | None = None,
        tools: ToolRegistry | None = None,
        max_steps: int = 5,
        save_history: bool = True,
    ):
        self.llm = llm
        self.memory = memory or Memory()
        self.tools = tools or default_tools(self.memory)
        self.max_steps = max_steps
        self.save_history = save_history
        if tools is None:
            self.tools.add(Tool(
                "ask_subagent",
                "Ask a focused helper MiniBot to solve a smaller subtask mid-turn.",
                {"task": "str"},
                self._ask_subagent,
            ))
            self.tools.add(Tool(
                "ask_subagents",
                "Ask multiple focused helper MiniBots to solve independent subtasks in parallel.",
                {"tasks": "list[str]"},
                self._ask_subagents,
            ))

    def run(self, query: str) -> str:
        steps: list[Step] = []
        for _ in range(self.max_steps):
            try:
                raw = self.llm.complete(self._messages(query, steps))
            except Exception as e:
                answer = (
                    "\u62b1\u6b49\uff0c\u6211\u8fd9\u6b21\u6ca1\u6709\u6210\u529f\u8c03\u7528 LLM \u6a21\u578b\uff0c"
                    "\u6240\u4ee5\u65e0\u6cd5\u7ee7\u7eed\u63a8\u7406\u3002\n"
                    f"\u5b9e\u9645\u539f\u56e0\uff1a{type(e).__name__}: {e}\n"
                    "\u8bf7\u68c0\u67e5 API Key\u3001base_url\u3001\u6a21\u578b\u540d\u6216\u7f51\u7edc\u8fde\u63a5\u540e\u518d\u8bd5\u3002"
                )
                self._save_turn(query, answer)
                return answer
            decision = self._parse(raw)

            if "final" in decision:
                answer = self._clean_final(str(decision["final"]))
                if not answer:
                    answer = self._unsupported_answer()
                steps.append(Step(thought=decision.get("thought", ""), final=answer))
                self._save_turn(query, answer)
                return answer

            action = decision.get("action")
            if not action:
                answer = self._unsupported_answer()
                self._save_turn(query, answer)
                return answer
            action_input = decision.get("action_input") or {}
            if not isinstance(action_input, dict):
                action_input = {}
            observation = self.tools.run(str(action), action_input)
            if observation.startswith("MISSING_TOOL:"):
                answer = self._missing_tool_answer(str(action))
                self._save_turn(query, answer)
                return answer
            steps.append(Step(
                thought=decision.get("thought", ""),
                action=str(action),
                action_input=action_input,
                observation=observation,
            ))

        answer = "I reached the step limit before finishing. Please simplify the task or raise max_steps."
        self._save_turn(query, answer)
        return answer

    def _messages(self, query: str, steps: list[Step]) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "Available tools:\n" + self.tools.prompt()},
            {"role": "system", "content": self.memory.build_context()},
            {"role": "user", "content": query},
            {"role": "assistant", "content": self._scratchpad(steps)},
        ]

    def _scratchpad(self, steps: list[Step]) -> str:
        if not steps:
            return "No previous steps."
        rows = []
        for i, s in enumerate(steps, 1):
            rows.append(f"Step {i} thought: {s.thought}")
            if s.action:
                rows.append(f"Action: {s.action}")
                rows.append(f"Action input: {json.dumps(s.action_input, ensure_ascii=False)}")
                rows.append(f"Observation: {s.observation}")
            if s.final:
                rows.append(f"Final: {s.final}")
        return "\n".join(rows)

    def _parse(self, raw: str) -> dict:
        text = self._extract_json_text(raw)
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
            try:
                data = json.loads(repaired)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                final = self._extract_field(text, "final")
                if final:
                    return {
                        "thought": self._extract_field(text, "thought") or "Recovered final from invalid JSON.",
                        "final": final,
                    }
        return {"thought": "LLM did not return valid JSON.", "final": raw}

    def _clean_final(self, answer: str) -> str:
        return answer.replace("\\l", "").strip()

    def _extract_json_text(self, raw: str) -> str:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        return text[start:end + 1] if start != -1 and end != -1 and end > start else text

    def _extract_field(self, text: str, name: str) -> str:
        match = re.search(rf'"{re.escape(name)}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.S)
        if not match:
            return ""
        return match.group(1).replace("\\n", "\n").replace("\\l", "")

    def _save_turn(self, query: str, answer: str) -> None:
        if not self.save_history:
            return
        self.memory.short.add("user", query)
        self.memory.short.add("assistant", answer)
        self.memory.history.add(query, answer)

    def _ask_subagent(self, task: str) -> str:
        child = MiniBot(
            self.llm,
            memory=self.memory,
            tools=default_tools(self.memory),
            max_steps=max(1, self.max_steps - 1),
            save_history=False,
        )
        return child.run(task)

    def _ask_subagents(self, tasks: list[str] | str) -> str:
        if isinstance(tasks, str):
            tasks = [tasks]
        if not isinstance(tasks, list) or not tasks:
            return "No subagent tasks provided."
        clean_tasks = [str(task).strip() for task in tasks if str(task).strip()]
        if not clean_tasks:
            return "No subagent tasks provided."
        results = asyncio.run(self._ask_subagents_async(clean_tasks))
        return json.dumps(results, ensure_ascii=False, indent=2)

    async def _ask_subagents_async(self, tasks: list[str]) -> list[dict[str, str]]:
        async def run_one(task: str) -> dict[str, str]:
            return {
                "task": task,
                "result": await asyncio.to_thread(self._ask_subagent, task),
            }

        return await asyncio.gather(*(run_one(task) for task in tasks))

    def _missing_tool_answer(self, name: str) -> str:
        return (
            f"\u6211\u73b0\u5728\u7f3a\u5c11 `{name}` \u8fd9\u4e2a\u5de5\u5177\uff0c"
            "\u6240\u4ee5\u4e0d\u80fd\u53ef\u9760\u5730\u83b7\u53d6\u8fd9\u7c7b\u771f\u5b9e\u6570\u636e\u3002\n"
            "\u6211\u4e0d\u4f1a\u7f16\u9020\u7ed3\u679c\u3002\u4f60\u53ef\u4ee5\u56de\u590d\u201c\u9700\u8981\u521b\u5efa\u201d\uff0c"
            "\u6211\u4f1a\u5728\u9879\u76ee\u91cc\u751f\u6210\u8fd9\u4e2a\u5de5\u5177\u7684\u6a21\u677f\uff1b"
            "\u751f\u6210\u540e\u9700\u8981\u914d\u7f6e\u771f\u5b9e API \u5730\u5740\u6216\u5728\u6a21\u677f\u91cc\u8865\u5145\u6570\u636e\u83b7\u53d6\u903b\u8f91\u3002"
        )

    def _unsupported_answer(self) -> str:
        return "\u62b1\u6b49\u4eb2\uff0c\u6682\u4e0d\u652f\u6301\u8be5\u529f\u80fd\u3002"
