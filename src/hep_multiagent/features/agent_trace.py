import os
from datetime import datetime


def format_elapsed(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    return f"+{mins:02d}:{secs:02d}"


def format_section(name: str, elapsed: str, content: str) -> str:
    return f"│ {name:<12} │ {elapsed} │ {content}\n"


def format_thought(content: str, limit: int = 300) -> str:
    preview = (content[:limit] + "...") if len(content) > limit else content
    return f"│              │        │   [Thought] {preview}\n"


def format_action(name: str, args: dict, result: str) -> str:
    args_str = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items())[:60]
    result_preview = (result or "")[:200].replace("\n", " ")
    return (
        f"│              │        │   [Action] {name}({args_str})\n"
        f"│              │        │   [Result] {result_preview}\n"
    )


class MarkdownLogger:
    def __init__(self):
        self._file = None
        self._start = None

    def init(self, output_dir: str) -> None:
        path = os.path.join(output_dir, "execution_log.md")
        self._file = open(path, "w")
        self._start = datetime.now()
        header = f"# Execution Log | {self._start.strftime('%Y-%m-%d %H:%M')}\n\n"
        header += "│ Node         │ Time   │ Details\n"
        header += "│" + "─" * 13 + "│" + "─" * 8 + "│" + "─" * 50 + "\n"
        self._file.write(header)
        self._file.flush()

    def _elapsed(self) -> str:
        if not self._start:
            return ""
        return format_elapsed((datetime.now() - self._start).total_seconds())

    def _write(self, text: str) -> None:
        if self._file:
            self._file.write(text)
            self._file.flush()

    def log(self, section: str, content: str) -> None:
        self._write(format_section(section, self._elapsed(), content[:100]))

    def iteration(self, current: int, max_iter: int) -> None:
        self._write(format_section("Iteration", self._elapsed(), f"{current}/{max_iter}"))

    def thought(self, content: str) -> None:
        if content:
            self._write(format_thought(content))

    def tool_call(self, name: str, args: dict, result: str) -> None:
        self._write(format_action(name, args, result))

    def error(self, error: Exception) -> None:
        self._write(format_section("ERROR", self._elapsed(), f"{type(error).__name__}: {error}"))

    def close(self) -> None:
        if self._file:
            total = format_elapsed((datetime.now() - self._start).total_seconds()) if self._start else ""
            self._file.write(f"│{'─' * 13}│{'─' * 8}│{'─' * 50}\n")
            self._file.write(f"│ DONE         │ {total} │ Total duration\n")
            self._file.close()
