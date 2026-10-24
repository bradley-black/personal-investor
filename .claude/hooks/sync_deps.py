"""PostToolUse hook: add third-party imports missing from pyproject.toml via `uv add`.

Reads the hook payload on stdin. Runs `uv add` (which updates pyproject.toml and
uv.lock together) for each imported top-level module that is not stdlib, not part
of this project, and not already a declared dependency.
"""

import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]

# Import name -> PyPI distribution name, where they differ.
ALIASES = {
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared(pyproject: dict) -> set[str]:
    specs = list(pyproject["project"].get("dependencies", []))
    for group in pyproject.get("dependency-groups", {}).values():
        specs += [s for s in group if isinstance(s, str)]
    return {normalize(re.split(r"[\s\[<>=!~;@(]", s, maxsplit=1)[0]) for s in specs}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def main() -> None:
    payload = json.load(sys.stdin)
    path = Path(payload["tool_input"]["file_path"]).resolve()
    if path.suffix != ".py" or not path.is_relative_to(PROJECT / "src"):
        return

    pyproject = tomllib.loads((PROJECT / "pyproject.toml").read_text())
    local = {normalize(pyproject["project"]["name"]), "personal-investor"}
    local |= {p.name for p in (PROJECT / "src").iterdir()}
    have = declared(pyproject)

    try:
        modules = imported_modules(path)
    except SyntaxError:
        return  # mid-edit file; the next edit will re-trigger

    missing = sorted(
        ALIASES.get(m, m)
        for m in modules
        if m not in sys.stdlib_module_names and m not in local
        and normalize(ALIASES.get(m, m)) not in have
    )

    notes = []
    for dist in missing:
        r = subprocess.run(["uv", "add", dist], cwd=PROJECT, capture_output=True, text=True)
        if r.returncode == 0:
            notes.append(f"uv add {dist}: added to pyproject.toml and uv.lock")
        else:
            notes.append(f"uv add {dist} FAILED (import name may differ from the PyPI name): "
                         f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}")

    if notes:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "Dependency sync hook: " + "; ".join(notes),
            }
        }))


main()
