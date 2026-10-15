"""
check_prompt_sync.py — verifies prompts.LIVE_PROMPT is still identical to the
prompt in ocr_pipeline.qwen_ocr_lines. Read-only: parses the source with `ast`,
never imports the live module.

    python finetune/check_prompt_sync.py [path/to/ocr_pipeline.py]
"""
import ast
import sys
from pathlib import Path

from prompts import LIVE_PROMPT

DEFAULT = Path(__file__).resolve().parent.parent / "ocr_pipeline.py"


def live_prompt(path: Path) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "qwen_ocr_lines":
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "prompt"
                ):
                    return ast.literal_eval(node.value)
    return None


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        print(f"SKIP: {path} not found (copy ocr_pipeline.py next to the repo root to check).")
        return 0
    live = live_prompt(path)
    if live is None:
        print("ERROR: could not find the `prompt` assignment in qwen_ocr_lines.")
        return 2
    if live == LIVE_PROMPT:
        print("OK: prompts.LIVE_PROMPT matches the live pipeline prompt.")
        return 0
    print("MISMATCH: the live pipeline prompt changed. Update finetune/prompts.py and retrain/re-evaluate.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
