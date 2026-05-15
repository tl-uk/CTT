#!/usr/bin/env python3
"""
Generate a Markdown project tree for CTT documentation/handoff.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUT = ROOT / "PROJECT_TREE.md"

# What to include
INCLUDE_PATTERNS = {
    ".py", ".cpp", ".hpp", ".h", ".proto", ".md",
    "CMakeLists.txt", "Makefile", "requirements.txt",
    ".yaml", ".yml", ".json", ".env",
}
# What to exclude
EXCLUDE_DIRS = {".git", ".venv", "build", "__pycache__", ".pytest_cache", "node_modules", ".idea", ".vscode"}

def should_include(path: Path) -> bool:
    if path.is_dir():
        # Include dir if it has descendants we care about
        return any(should_include(p) for p in path.iterdir() if p.name not in EXCLUDE_DIRS)
    return path.name in INCLUDE_PATTERNS or path.suffix in INCLUDE_PATTERNS

def build_tree(path: Path, prefix: str = "", is_last: bool = True) -> str:
    lines = []
    display = f"{'└── ' if is_last else '├── '}{path.name}"
    lines.append(prefix + display)

    if path.is_dir():
        children = sorted([p for p in path.iterdir() if p.name not in EXCLUDE_DIRS and should_include(p)])
        for i, child in enumerate(children):
            is_last_child = i == len(children) - 1
            extension = "    " if is_last else "│   "
            lines.extend(build_tree(child, prefix + extension, is_last_child))
    return lines

if __name__ == "__main__":
    tree_lines = [f"# CTT Project Structure\n", f"**Generated:** {os.popen('date').read().strip()}\n", "```"]
    tree_lines.extend(build_tree(ROOT))
    tree_lines.append("```")

    OUTPUT.write_text("\n".join(tree_lines))
    print(f"✅ Written to {OUTPUT}")