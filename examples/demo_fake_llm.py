from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minibot import MiniBot
from minibot.llm import FakeLLM


llm = FakeLLM([
    '{"thought":"need exact math","action":"calculator","action_input":{"expression":"2+3*4"}}',
    '{"thought":"calculation observed","final":"2 + 3 * 4 = 14"}',
])

bot = MiniBot(llm)
print(bot.run("2 + 3 * 4 等于多少？"))
