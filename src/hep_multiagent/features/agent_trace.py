import os
from datetime import datetime


class MarkdownLogger:
    def __init__(self):
        self._file = None
        self._start = None

    def init(self, output_dir: str) -> None:
        path = os.path.join(output_dir, "execution_log.md")
        self._file = open(path, "w")
        self._start = datetime.now()
        self._file.write(f"# Execution Log\n\nStarted: {self._start}\n\n")
        self._file.flush()

    def _elapsed(self) -> str:
        if not self._start:
            return ""
        delta = datetime.now() - self._start
        mins, secs = divmod(int(delta.total_seconds()), 60)
        return f"[+{mins:02d}:{secs:02d}]"

    def log(self, section: str, content: str) -> None:
        if self._file:
            self._file.write(f"## {self._elapsed()} {section}\n\n{content}\n\n---\n\n")
            self._file.flush()

    def iteration(self, current: int, max_iter: int) -> None:
        if self._file:
            self._file.write(f"### {self._elapsed()} Iteration {current}/{max_iter}\n\n")
            self._file.flush()

    def thought(self, content: str) -> None:
        if self._file and content:
            preview = content[:300] + "..." if len(content) > 300 else content
            self._file.write(f"**Reasoning**: {preview}\n\n")
            self._file.flush()

    def tool_call(self, name: str, args: dict, result: str) -> None:
        if self._file:
            args_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in args.items())
            result_preview = result[:500] if result else "(empty)"
            self._file.write(f"**Action**: `{name}({args_str})`\n\n")
            self._file.write(f"**Observation**:\n```\n{result_preview}\n```\n\n")
            self._file.flush()

    def error(self, error: Exception) -> None:
        if self._file:
            self._file.write(f"## {self._elapsed()} ERROR\n\n**{type(error).__name__}**: {error}\n\n---\n\n")
            self._file.flush()

    def close(self) -> None:
        if self._file:
            self._file.write(f"\nEnded: {datetime.now()}\n")
            self._file.close()
