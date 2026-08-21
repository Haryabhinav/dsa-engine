"""Subprocess wrapper: run a target script and report the line numbers it executed.

Uses sys.settrace rather than the `coverage` package so the engine has zero
third-party dependencies on day 1. Emits a sentinel-prefixed JSON line on stderr
so normal stderr from the program under test stays readable.
"""
import json
import os
import runpy
import sys

SENTINEL = "__COV__"


def main() -> None:
    target = os.path.abspath(sys.argv[1])
    sys.argv = [target] + sys.argv[2:]
    seen: set[int] = set()

    def local(frame, event, arg):
        if event == "line":
            seen.add(frame.f_lineno)
        return local

    def glob(frame, event, arg):
        if os.path.abspath(frame.f_code.co_filename) == target:
            seen.add(frame.f_lineno)
            return local
        return None

    sys.settrace(glob)
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit:
        pass
    finally:
        sys.settrace(None)
        sys.stderr.write("\n" + SENTINEL + json.dumps(sorted(seen)) + "\n")


main()
