from pathlib import Path
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from minibot import MiniBot
from minibot.agent import SYSTEM_PROMPT
from minibot.config import load_env_file
from minibot.llm import FakeLLM
from minibot.llm import OpenAICompatibleLLM
from minibot.memory import Memory
from minibot.rag import SimpleRAG
from minibot.tools import ToolRegistry, default_tools, get_weather, load_custom_tools
from minibot.cli import bot_header, help_text, main, rejects_create_tool, render_banner, render_banner_mascots, run_with_spinner, user_prompt, wants_create_tool
from minibot.tool_builder import scaffold_http_tool


class BrokenLLM:
    def complete(self, messages):
        raise RuntimeError("bad api")


class FakeCliLLM(FakeLLM):
    model = "test-model"
    base_url = "https://example.test/v1"


class SlowEchoLLM:
    def __init__(self, delay=0.2):
        self.delay = delay
        self.thread_ids = set()
        self.lock = threading.Lock()

    def complete(self, messages):
        with self.lock:
            self.thread_ids.add(threading.get_ident())
        time.sleep(self.delay)
        query = next(m["content"] for m in messages if m["role"] == "user")
        return '{"thought":"done","final":"done: ' + query + '"}'


class MiniBotTest(unittest.TestCase):
    def test_system_prompt_sets_personal_agent_identity(self):
        self.assertIn("dedicated personal intelligent agent", SYSTEM_PROMPT)
        self.assertIn("not a generic teaching assistant", SYSTEM_PROMPT)

    def test_agent_calls_tool_then_final(self):
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            llm = FakeLLM([
                '{"thought":"need math","action":"calculator","action_input":{"expression":"2+3*4"}}',
                '{"thought":"calculation observed","final":"14"}',
            ])
            memory = Memory(tmp_path / "memory")
            bot = MiniBot(llm, memory=memory)

            self.assertEqual(bot.run("2+3*4=?"), "14")
            history = (tmp_path / "memory" / "history.jsonl").read_text(encoding="utf-8")
            self.assertIn("2+3*4=?", history)

    def test_agent_can_call_subagent_mid_turn(self):
        llm = FakeLLM([
            '{"thought":"delegate small task","action":"ask_subagent","action_input":{"task":"2+3*4=?"}}',
            '{"thought":"need math","action":"calculator","action_input":{"expression":"2+3*4"}}',
            '{"thought":"subtask done","final":"14"}',
            '{"thought":"use subagent result","final":"subagent says 14"}',
        ])
        bot = MiniBot(llm, memory=Memory(Path(tempfile.mkdtemp()) / "memory"))

        self.assertEqual(bot.run("ask a helper to calculate 2+3*4"), "subagent says 14")
        self.assertIn("ask_subagent", bot.tools.tools)

    def test_agent_can_call_subagents_in_parallel(self):
        llm = SlowEchoLLM(delay=0.2)
        bot = MiniBot(llm, memory=Memory(Path(tempfile.mkdtemp()) / "memory"))

        started = time.perf_counter()
        result = bot.tools.run("ask_subagents", {"tasks": ["alpha", "beta", "gamma"]})
        elapsed = time.perf_counter() - started

        self.assertIn("done: alpha", result)
        self.assertIn("done: beta", result)
        self.assertIn("done: gamma", result)
        self.assertGreaterEqual(len(llm.thread_ids), 2)
        self.assertLess(elapsed, 0.5)

    def test_agent_recovers_invalid_json_final(self):
        llm = FakeLLM([
            '{"thought":"bad slash","final":"line 1\\nline 2\\l"}',
        ])
        bot = MiniBot(llm, memory=Memory(Path(tempfile.mkdtemp()) / "memory"))

        self.assertEqual(bot.run("test"), "line 1\nline 2")

    def test_agent_falls_back_when_final_is_empty(self):
        llm = FakeLLM([
            '{"thought":"unsupported","final":""}',
        ])
        bot = MiniBot(llm, memory=Memory(Path(tempfile.mkdtemp()) / "memory"))

        self.assertEqual(bot.run("test"), "\u62b1\u6b49\u4eb2\uff0c\u6682\u4e0d\u652f\u6301\u8be5\u529f\u80fd\u3002")

    def test_agent_falls_back_when_llm_fails(self):
        bot = MiniBot(BrokenLLM(), memory=Memory(Path(tempfile.mkdtemp()) / "memory"))
        answer = bot.run("hello")
        self.assertIn("\u6ca1\u6709\u6210\u529f\u8c03\u7528 LLM \u6a21\u578b", answer)
        self.assertIn("bad api", answer)

    def test_agent_falls_back_when_tool_is_missing(self):
        llm = FakeLLM([
            '{"thought":"need stock","action":"get_stock_price","action_input":{"query":"AAPL"}}',
        ])
        tools = ToolRegistry([])
        bot = MiniBot(llm, memory=Memory(Path(tempfile.mkdtemp()) / "memory"), tools=tools)
        answer = bot.run("AAPL stock price?")
        self.assertIn("\u7f3a\u5c11 `get_stock_price`", answer)
        self.assertEqual(tools.last_missing_tool, "get_stock_price")

    def test_memory_tool(self):
        with tempfile.TemporaryDirectory() as d:
            memory = Memory(Path(d) / "memory")
            tools = default_tools(memory)

            self.assertEqual(tools.run("remember", {"text": "user likes Python agents"}), "saved")
            self.assertIn("Python", tools.run("search_memory", {"query": "Python"}))

    def test_weather_tool_is_registered(self):
        tools = default_tools(Memory(Path(tempfile.mkdtemp()) / "memory"))
        self.assertIn("get_weather", tools.tools)

    def test_weather_tool_supports_tomorrow(self):
        payload = {
            "current_condition": [{
                "weatherDesc": [{"value": "Sunny"}],
                "temp_C": "20",
                "FeelsLikeC": "20",
                "humidity": "50",
                "windspeedKmph": "8",
            }],
            "nearest_area": [{"areaName": [{"value": "Shanghai"}]}],
            "weather": [
                {"date": "2026-05-07", "avgtempC": "20", "mintempC": "16", "maxtempC": "24", "hourly": []},
                {
                    "date": "2026-05-08",
                    "avgtempC": "22",
                    "mintempC": "18",
                    "maxtempC": "26",
                    "hourly": [{
                        "time": "1200",
                        "weatherDesc": [{"value": "Cloudy"}],
                        "humidity": "61",
                        "windspeedKmph": "12",
                    }],
                },
            ],
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                import json
                return json.dumps(payload).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = get_weather("\u4e0a\u6d77", date="tomorrow")

        self.assertIn("date=2026-05-08", result)
        self.assertIn("weather=Cloudy", result)
        self.assertIn("avg_temperature_c=22", result)

    def test_cli_banner_mentions_model_and_commands(self):
        banner = render_banner("demo-model", "https://example.test/v1")
        self.assertIn("Welcome to our minibot agent", banner)
        self.assertIn("The best first agent assistant for beginners", banner)
        self.assertIn("demo-model", banner)
        self.assertIn("/exit", banner)
        self.assertIn("/create-tool", banner)
        self.assertIn("pixel cat", banner)
        self.assertIn("pixel dog", banner)
        self.assertIn("user asks", banner)
        self.assertIn("minibot thinks", banner)
        self.assertIn("\033[48;2;", banner)
        for line in banner.splitlines()[2:4]:
            self.assertTrue(line.startswith("| "))
            self.assertTrue(line.endswith(" |"))

    def test_banner_mascots_use_mosaic_avatars(self):
        mascots = render_banner_mascots()

        self.assertIn("user asks", mascots)
        self.assertIn("minibot thinks", mascots)
        self.assertIn("\033[48;2;", mascots)

    def test_cli_prompts_use_mosaic_avatars(self):
        self.assertIn("You> ", user_prompt())
        self.assertIn("MiniBot>", bot_header())
        self.assertIn("\033[48;2;", user_prompt())
        self.assertIn("\033[48;2;", bot_header())

    def test_cli_entrypoint_accepts_cli_subcommand(self):
        with patch("minibot.cli.run_cli") as run_cli:
            main(["cli"])

        run_cli.assert_called_once_with()

    def test_cli_entrypoint_prints_help(self):
        with patch("builtins.print") as print_mock:
            main(["--help"])

        self.assertIn("minibot cli", help_text())
        print_mock.assert_called_once_with(help_text())

    def test_cli_prints_farewell_on_exit_commands(self):
        for command in ["/exit", "/quit"]:
            with patch("minibot.cli.OpenAICompatibleLLM", return_value=FakeCliLLM([])):
                with patch("builtins.input", return_value=command):
                    with patch("builtins.print") as print_mock:
                        main(["cli"])

            printed = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
            self.assertIn("Goodbye, see you next time~", printed)

    def test_run_with_spinner_returns_bot_answer(self):
        bot = MiniBot(FakeLLM(['{"thought":"done","final":"ok"}']), memory=Memory(Path(tempfile.mkdtemp()) / "memory"))

        self.assertEqual(run_with_spinner(bot, "hello"), "ok")

    def test_local_env_file_loads_llm_config(self):
        old_values = {k: os.environ.get(k) for k in ["OPENAI_API_KEY", "OPENAI_BASE_URL", "MINIBOT_MODEL"]}
        try:
            for key in old_values:
                os.environ.pop(key, None)
            with tempfile.TemporaryDirectory() as d:
                env_file = Path(d) / "minibot.local.env"
                env_file.write_text(
                    "\n".join([
                        "OPENAI_API_KEY=test-key",
                        "OPENAI_BASE_URL=https://example.test/v1",
                        "MINIBOT_MODEL=test-model",
                    ]),
                    encoding="utf-8",
                )

                load_env_file(env_file)
                llm = OpenAICompatibleLLM()

            self.assertEqual(llm.api_key, "test-key")
            self.assertEqual(llm.base_url, "https://example.test/v1")
            self.assertEqual(llm.model, "test-model")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_wants_create_tool(self):
        self.assertTrue(wants_create_tool("\u9700\u8981\u521b\u5efa"))
        self.assertTrue(wants_create_tool("/create-tool"))
        self.assertTrue(wants_create_tool("yes"))
        self.assertFalse(wants_create_tool("\u4e0d\u7528"))
        self.assertTrue(rejects_create_tool("\u4e0d\u7528"))

    def test_scaffold_and_load_custom_tool(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "custom_tools.py"
            tool_name = scaffold_http_tool("get stock price", path)
            registry = ToolRegistry([])
            load_custom_tools(registry, path)

            self.assertEqual(tool_name, "get_stock_price")
            self.assertIn("get_stock_price", registry.tools)
            result = registry.run("get_stock_price", {"query": "AAPL"})
            self.assertIn("no real data source is configured", result)

    def test_simple_rag_search(self):
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs"
            docs.mkdir()
            (docs / "a.md").write_text("minibot uses ReAct and tool calls.", encoding="utf-8")

            rag = SimpleRAG(docs)
            results = rag.search("ReAct tool")
            self.assertEqual(len(results), 1)
            self.assertIn("minibot", results[0].text)


if __name__ == "__main__":
    unittest.main()
