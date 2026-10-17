#!/usr/bin/env python3
"""Збирає tools/studio_patch.lua — один скрипт для Command Bar у Studio, який
замінює код вказаних файлів прямо у твоєму місці (AssetConfig та інші твої
зміни лишаються недоторканими).

Використання (з папки AnimeDiceAwakening):
    python3 tools/make_studio_patch.py [--with-models] src/шлях/до/файлу.lua ...

--with-models — додати в кінець завантаження моделей героїв (load_hero_models.lua).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tools", "studio_patch.lua")

# Папки src/ → сервіси Studio (як у default.project.json)
MOUNTS = [
    ("src/StarterPlayer/StarterPlayerScripts/", ["StarterPlayer", "StarterPlayerScripts"]),
    ("src/ReplicatedStorage/", ["ReplicatedStorage"]),
    ("src/ServerScriptService/", ["ServerScriptService"]),
]


def long_string(text):
    level = 1
    while ("]" + "=" * level + "]") in text:
        level += 1
    eq = "=" * level
    return "[" + eq + "[\n" + text + "]" + eq + "]"


def describe(rel):
    rel = rel.replace(os.sep, "/")
    for prefix, base in MOUNTS:
        if rel.startswith(prefix):
            parts = rel[len(prefix):].split("/")
            name = parts[-1]
            if name.endswith(".server.lua"):
                cls, name = "Script", name[: -len(".server.lua")]
            elif name.endswith(".client.lua"):
                cls, name = "LocalScript", name[: -len(".client.lua")]
            elif name.endswith(".lua"):
                cls, name = "ModuleScript", name[: -len(".lua")]
            else:
                raise SystemExit("не .lua файл: " + rel)
            return base + parts[:-1] + [name], cls
    raise SystemExit("файл поза src/ReplicatedStorage, ServerScriptService чи StarterPlayerScripts: " + rel)


def main(argv):
    with_models = "--with-models" in argv
    files = [a for a in argv if a != "--with-models"]
    if not files:
        raise SystemExit(__doc__)

    out = [
        "-- Згенеровано tools/make_studio_patch.py — НЕ редагуй вручну.",
        "-- Studio → зупини гру (Stop) → View → Command Bar → встав увесь текст → ▶ Run.",
        "-- Замінює код скриптів нижче на нову версію. Ctrl+Z скасовує зміни.",
        'local ChangeHistoryService = game:GetService("ChangeHistoryService")',
        'local ScriptEditorService = game:GetService("ScriptEditorService")',
        "local recording = ChangeHistoryService:TryBeginRecording(\"AnimeDiceAwakening patch\")",
        "",
        "local function setSource(path, className, source)",
        "\tlocal parent = game:GetService(path[1])",
        "\tfor i = 2, #path - 1 do",
        "\t\tlocal child = parent:FindFirstChild(path[i])",
        "\t\tif not child then",
        "\t\t\tchild = Instance.new(\"Folder\")",
        "\t\t\tchild.Name = path[i]",
        "\t\t\tchild.Parent = parent",
        "\t\tend",
        "\t\tparent = child",
        "\tend",
        "\tlocal target = parent:FindFirstChild(path[#path])",
        "\tif target and not target:IsA(className) then",
        "\t\twarn(\"❌ \" .. target:GetFullName() .. \" — не \" .. className .. \", пропускаю\")",
        "\t\treturn",
        "\tend",
        "\tif not target then",
        "\t\ttarget = Instance.new(className)",
        "\t\ttarget.Name = path[#path]",
        "\t\ttarget.Parent = parent",
        "\tend",
        "\t-- Через ScriptEditorService, щоб оновились і відкриті вкладки редактора",
        "\tlocal ok = pcall(function()",
        "\t\tScriptEditorService:UpdateSourceAsync(target, function()",
        "\t\t\treturn source",
        "\t\tend)",
        "\tend)",
        "\tif not ok then",
        "\t\ttarget.Source = source",
        "\tend",
        "\tprint(\"✅ оновлено \" .. target:GetFullName())",
        "end",
        "",
    ]
    for rel in files:
        path, cls = describe(rel)
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            source = f.read()
        lua_path = "{ " + ", ".join('"%s"' % p for p in path) + " }"
        out.append("setSource(%s, \"%s\", %s)" % (lua_path, cls, long_string(source)))
        out.append("")

    out += [
        "if recording then",
        "\tChangeHistoryService:FinishRecording(recording, Enum.FinishRecordingOperation.Commit)",
        "end",
    ]

    if with_models:
        with open(os.path.join(ROOT, "tools", "load_hero_models.lua"), encoding="utf-8") as f:
            loader = f.read()
        out += ["", "-- Моделі героїв з Creator Store (tools/load_hero_models.lua)", "do", loader, "end"]

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("Записано", os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main(sys.argv[1:])
