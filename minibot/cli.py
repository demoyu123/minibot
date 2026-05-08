from __future__ import annotations

import itertools
import sys
import threading
import time

from minibot.agent import MiniBot
from minibot.config import load_env_file
from minibot.llm import OpenAICompatibleLLM
from minibot.tool_builder import CUSTOM_TOOLS_PATH, scaffold_http_tool
from minibot.tools import load_custom_tools


RESET = "\033[0m"
CAT = "Cat"
DOG = "Dog"
BANNER_WIDTH = 60
CAT_MOSAIC = [
    "  P   P  ",
    " PWPWPWP ",
    "PWWKWWKWP",
    "PWWRWRWWP",
]
DOG_MOSAIC = [
    " O     O ",
    "OYYWYYYO",
    "YWWKWWKY",
    "YYWBNWYY",
]
PALETTE = {
    "B": (92, 49, 28),
    "K": (35, 22, 18),
    "N": (82, 40, 26),
    "O": (154, 92, 46),
    "P": (252, 179, 188),
    "R": (246, 91, 104),
    "W": (255, 244, 220),
    "Y": (241, 168, 83),
}


def center_line(text: str) -> str:
    return "| " + text.center(BANNER_WIDTH - 4) + " |"


def render_mosaic(rows: list[str]) -> str:
    rendered = []
    for row in rows:
        cells = []
        for cell in row:
            color = PALETTE.get(cell)
            cells.append(" " if not color else f"{bg(color)} {RESET}")
        rendered.append("".join(cells).rstrip())
    return "\n".join(rendered)


def render_mosaic_lines(rows: list[str]) -> list[str]:
    return render_mosaic(rows).splitlines()


def bg(rgb: tuple[int, int, int]) -> str:
    return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def user_prompt() -> str:
    return f"\n{render_mosaic(CAT_MOSAIC)}\n{CAT} You> "


def bot_header() -> str:
    return f"\n{render_mosaic(DOG_MOSAIC)}\n{DOG} MiniBot>\n"


def visible_len(text: str) -> int:
    count = 0
    in_escape = False
    for ch in text:
        if ch == "\033":
            in_escape = True
            continue
        if in_escape:
            if ch == "m":
                in_escape = False
            continue
        count += 1
    return count


def pad_visible(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_len(text))


def render_banner_mascots() -> str:
    cat_lines = render_mosaic_lines(CAT_MOSAIC)
    dog_lines = render_mosaic_lines(DOG_MOSAIC)
    rows = []
    for i, (cat_line, dog_line) in enumerate(zip(cat_lines, dog_lines)):
        cat_label = "  user asks" if i == 1 else ""
        dog_label = "  minibot thinks" if i == 1 else ""
        rows.append(
            "  "
            + pad_visible(cat_line + cat_label, 31)
            + pad_visible(dog_line + dog_label, 35)
        )
    return "\n".join(rows)


class ThinkingSpinner:
    def __init__(self, text: str = "MiniBot is thinking..."):
        self.text = text
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if sys.stdout.isatty():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self._thread:
            return
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r" + " " * (len(self.text) + 4) + "\r")
        sys.stdout.flush()

    def _spin(self) -> None:
        for frame in itertools.cycle("|/-\\"):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{frame} {self.text}")
            sys.stdout.flush()
            time.sleep(0.12)


def run_with_spinner(bot: MiniBot, query: str) -> str:
    with ThinkingSpinner():
        return bot.run(query)


def render_banner(model: str, base_url: str) -> str:
    return f"""
+------------------------------------------------------------+
{center_line("Welcome to our minibot agent")}
{center_line("The best first agent assistant for beginners")}
+------------------------------------------------------------+

{render_banner_mascots()}

Commands:
  /exit       quit minibot
  /create-tool create the missing tool from the previous answer

Prompt style:
  pixel cat     You>       your message
  pixel dog     MiniBot>   minibot answer

Runtime:
  model       {model}
  base_url    {base_url}
  memory      ./memory
  docs        ./data/docs
"""


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in {"-h", "--help", "help"}:
        print(help_text())
        return
    if argv and argv[0] != "cli":
        print(f"Unknown command: {argv[0]}\n")
        print(help_text())
        return
    run_cli()


def help_text() -> str:
    return """Usage:
  minibot cli      start the minibot chat CLI
  minibot          start the minibot chat CLI
  minibot --help   show this help
"""


def run_cli() -> None:
    load_env_file()
    llm = OpenAICompatibleLLM()
    bot = MiniBot(llm)
    pending_tool = ""
    print(render_banner(llm.model, llm.base_url))
    while True:
        try:
            query = input(user_prompt()).strip()
        except EOFError:
            print()
            break
        if query in {"/exit", "/quit", "exit", "quit"}:
            print(f"{bot_header()}Goodbye, see you next time~")
            break
        if not query:
            continue

        if pending_tool and wants_create_tool(query):
            tool_name = scaffold_http_tool(pending_tool)
            load_custom_tools(bot.tools, CUSTOM_TOOLS_PATH)
            pending_tool = ""
            print(
                bot_header() +
                f"\u5df2\u521b\u5efa\u5de5\u5177 `{tool_name}`\uff1a{CUSTOM_TOOLS_PATH}\n"
                "\u5b83\u5df2\u7ecf\u6ce8\u518c\u5230\u5f53\u524d\u4f1a\u8bdd\u3002"
                "\u8981\u83b7\u53d6\u771f\u5b9e\u6570\u636e\uff0c\u8bf7\u914d\u7f6e\u5bf9\u5e94\u7684 "
                f"`MINIBOT_TOOL_{tool_name.upper()}_URL` \u73af\u5883\u53d8\u91cf\uff0c"
                "\u6216\u76f4\u63a5\u7f16\u8f91\u8fd9\u4e2a\u5de5\u5177\u51fd\u6570\u3002"
            )
            continue
        if pending_tool and rejects_create_tool(query):
            print(
                bot_header() +
                f"\u597d\u7684\uff0c\u6211\u4e0d\u4f1a\u521b\u5efa `{pending_tool}`\u3002"
                "\u4f60\u53ef\u4ee5\u7ee7\u7eed\u95ee\u5176\u4ed6\u95ee\u9898\u3002"
            )
            pending_tool = ""
            continue

        print(f"{bot_header()}{run_with_spinner(bot, query)}")
        pending_tool = bot.tools.last_missing_tool


def wants_create_tool(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {
        "/create-tool",
        "\u9700\u8981",
        "\u9700\u8981\u521b\u5efa",
        "\u521b\u5efa",
        "\u5e2e\u6211\u521b\u5efa",
        "\u662f",
        "yes",
        "y",
        "ok",
    }


def rejects_create_tool(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {
        "\u4e0d\u9700\u8981",
        "\u4e0d\u7528",
        "\u4e0d\u8981",
        "\u5148\u4e0d\u7528",
        "no",
        "n",
    }


if __name__ == "__main__":
    main()
