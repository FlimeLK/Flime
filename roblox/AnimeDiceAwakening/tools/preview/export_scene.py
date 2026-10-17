#!/usr/bin/env python3
"""Збирає джерела гри + export_scene.luau в один файл, запускає `luau` і друкує JSON сцени.

Використання: python3 tools/preview/export_scene.py [шлях/до/luau] > scene.json
"""
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def main() -> int:
    luau = sys.argv[1] if len(sys.argv) > 1 else "luau"
    parts = ["local G = {}", f'G.ROOT = "{SRC.as_posix()}/"', "G.SOURCES = {}"]
    for path in sorted(SRC.rglob("*.lua")):
        parts.append(f'G.SOURCES["{path.as_posix()}"] = [========[{path.read_text(encoding="utf-8")}]========]')
    parts.append((pathlib.Path(__file__).parent / "export_scene.luau").read_text(encoding="utf-8"))
    with tempfile.NamedTemporaryFile("w", suffix=".luau", delete=False, encoding="utf-8") as bundle:
        bundle.write("\n".join(parts))
    return subprocess.call([luau, bundle.name])


if __name__ == "__main__":
    sys.exit(main())
