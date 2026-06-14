from __future__ import annotations

import builtins
import sys
from datetime import datetime


_ORIGINAL_PRINT = builtins.print
_INSTALLED = False


def _prefix_message(message: str, level: str) -> str:
    if not message:
        return message

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"{timestamp}  {level} "

    index = 0
    while index < len(message) and message[index] in "\r\n":
        index += 1

    return message[:index] + prefix + message[index:]


def install_timestamped_print(level: str = "INFO") -> None:
    global _INSTALLED

    if _INSTALLED:
        return

    def timestamped_print(*args, sep=" ", end="\n", file=None, flush=False):
        if file is not None and file not in {sys.stdout, sys.stderr}:
            _ORIGINAL_PRINT(*args, sep=sep, end=end, file=file, flush=flush)
            return

        if not args:
            _ORIGINAL_PRINT(sep=sep, end=end, file=file, flush=flush)
            return

        message = sep.join(str(arg) for arg in args)
        _ORIGINAL_PRINT(_prefix_message(message, level), end=end, file=file, flush=flush)

    builtins.print = timestamped_print
    _INSTALLED = True
