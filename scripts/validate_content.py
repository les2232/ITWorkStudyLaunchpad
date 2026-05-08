from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODULES_DIR = PROJECT_ROOT / "content" / "modules"

REQUIRED_MODULE_HEADINGS = [
    "## Goal",
    "## Plain-Language Explanation",
    "## Why This Matters",
    "## Key Terms",
    "## Common Beginner Mistakes",
    "## When to Ask for Help",
    "## Quick Check",
    "## Strong Answers",
    "## Related Modules",
]

COMMON_IT_WORDS_REQUIRED_TERMS = [
    "### Domain",
    "### SCCM / Configuration Manager",
    "### Imaging",
    "### Ticket",
    "### Asset Tag",
    "### Escalation",
    "### Mentor / Buddy",
    "### Documentation",
]


def check_balanced_code_fences(text: str, path: Path) -> list[str]:
    fence_count = text.count("```")
    if fence_count % 2 != 0:
        return [f"{path}: unbalanced markdown code fences"]
    return []


def check_no_todos(text: str, path: Path) -> list[str]:
    if "TODO" in text:
        return [f"{path}: contains TODO"]
    return []


def check_required_headings(text: str, path: Path) -> list[str]:
    errors = []
    for heading in REQUIRED_MODULE_HEADINGS:
        if heading not in text:
            errors.append(f"{path}: missing required heading: {heading}")
    return errors


def check_common_it_words_terms(text: str, path: Path) -> list[str]:
    errors = []
    for term in COMMON_IT_WORDS_REQUIRED_TERMS:
        if term not in text:
            errors.append(f"{path}: missing required glossary term: {term}")
    return errors


def validate_modules() -> list[str]:
    errors = []

    if not MODULES_DIR.exists():
        return [f"Missing modules directory: {MODULES_DIR}"]

    module_files = sorted(MODULES_DIR.glob("*.md"))

    if not module_files:
        return [f"No module files found in {MODULES_DIR}"]

    for path in module_files:
        text = path.read_text(encoding="utf-8")

        errors.extend(check_balanced_code_fences(text, path))
        errors.extend(check_no_todos(text, path))
        errors.extend(check_required_headings(text, path))

        if path.name == "common_it_words.md":
            errors.extend(check_common_it_words_terms(text, path))

    return errors


def main() -> int:
    errors = validate_modules()

    if errors:
        print("Content validation failed:\n")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Content validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())