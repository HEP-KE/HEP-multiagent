import os
import textwrap
from datetime import datetime


class MarkdownLogger:
    def __init__(self, wrap_width: int = 80):
        self._file = None
        self._start = None
        self._current_node = None
        self._wrap_width = wrap_width

    def init(self, output_dir: str) -> None:
        path = os.path.join(output_dir, "execution_log.md")
        self._file = open(path, "w")
        self._start = datetime.now()
        self._file.write(f"# Execution Log | {self._start.strftime('%Y-%m-%d %H:%M')}\n\n")
        self._file.write(f"{'NODE':<14} {'TIME':<8} DETAILS\n")
        self._file.write(f"{'-'*14} {'-'*8} {'-'*56}\n")
        self._file.flush()

    def _elapsed(self) -> str:
        if not self._start:
            return "+00:00"
        mins, secs = divmod(int((datetime.now() - self._start).total_seconds()), 60)
        return f"+{mins:02d}:{secs:02d}"

    def _wrap_text(self, text: str) -> list:
        lines = []
        for paragraph in text.split('\n'):
            if not paragraph.strip():
                lines.append("")
            else:
                wrapped = textwrap.wrap(paragraph, width=self._wrap_width)
                lines.extend(wrapped if wrapped else [""])
        return lines

    def _write_line(self, content: str, node: str = None) -> None:
        if not self._file:
            return
        show_node = ""
        if node and node != self._current_node:
            show_node = node
            self._current_node = node

        wrapped_lines = self._wrap_text(content)
        for i, line in enumerate(wrapped_lines):
            if i == 0:
                self._file.write(f"{show_node:<14} {self._elapsed():<8} {line}\n")
            else:
                self._file.write(f"{'':<14} {'':<8} {line}\n")
        self._file.flush()

    def log(self, node: str, content: str) -> None:
        self._write_line(content, node)

    def thinking(self) -> None:
        self._write_line("[Thinking...]")

    def thought(self, content: str) -> None:
        if content:
            self._write_line(f"[Thought] {content}")

    def tool_start(self, name: str, args: dict) -> None:
        args_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in args.items())
        self._write_line(f"[Running] {name}({args_str})...")

    def tool_call(self, name: str, args: dict, result: str) -> None:
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
        self._write_line(f"[Action] {name}({args_str})")
        self._write_line(f"[Result] {result}")

    def error(self, err: Exception) -> None:
        self._write_line(f"{type(err).__name__}: {err}", "ERROR")

    def close(self) -> None:
        if self._file:
            self._file.write(f"{'-'*14} {'-'*8} {'-'*56}\n")
            self._write_line(f"Total time: {self._elapsed()}", "COMPLETE")
            self._file.close()
