#!/usr/bin/env python3
"""One-off: replace typographic dashes with ASCII hyphen-minus."""
import pathlib

root = pathlib.Path(__file__).resolve().parent
pairs = [
    ("\u2014", "-"),
    ("\u2013", "-"),
    ("\u2011", "-"),
    ("\u2010", "-"),
    ("\u2212", "-"),
    ("\u2015", "-"),
]
skip_dir_names = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
skip_suffixes = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp3", ".mp4", ".pdf", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".zip", ".7z", ".rar", ".exe", ".dll",
    ".so", ".dylib", ".pyc", ".pyo",
}


def should_skip(path: pathlib.Path) -> bool:
    for part in path.parts:
        if part in skip_dir_names:
            return True
    if path.suffix.lower() in skip_suffixes:
        return True
    return False


def main() -> None:
    changed: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file() or should_skip(p):
            continue
        if p.name == "_replace_dashes.py":
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if len(data) > 50 * 1024 * 1024:
            continue
        sample = data[:16384]
        if b"\x00" in sample and p.suffix.lower() not in {".sql"}:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        new = text
        for a, b in pairs:
            new = new.replace(a, b)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed.append(str(p.relative_to(root)))
    print(f"Updated {len(changed)} files")
    for c in sorted(changed):
        print(c)


if __name__ == "__main__":
    main()
