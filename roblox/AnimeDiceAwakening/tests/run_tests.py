#!/usr/bin/env python3
"""Bundle game sources + mocks into one Luau file and run it with the `luau` CLI.

Usage: python3 tests/run_tests.py [path/to/luau]
The luau CLI (no Roblox needed): https://github.com/luau-lang/luau/releases
"""
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def main() -> int:
    luau = sys.argv[1] if len(sys.argv) > 1 else "luau"
    parts = ["local G = {}", f'G.ROOT = "{SRC.as_posix()}/"', "G.SOURCES = {}"]
    for path in sorted(SRC.rglob("*.lua")):
        parts.append(f'G.SOURCES["{path.as_posix()}"] = [========[{path.read_text(encoding="utf-8")}]========]')
    parts.append((TESTS / "harness.luau").read_text(encoding="utf-8"))
    for test in sorted(TESTS.glob("*.test.luau")):
        parts.append("do\n" + test.read_text(encoding="utf-8") + "\nend")
    with tempfile.NamedTemporaryFile("w", suffix=".luau", delete=False, encoding="utf-8") as bundle:
        bundle.write("\n".join(parts))
    return subprocess.call([luau, bundle.name])


if __name__ == "__main__":
    sys.exit(main())
