"""
Static check: enforce 'no simulated/mock/fake data outside tests'.

This is the most important rule in the project. Research findings made on
synthetic data that was supposed to be real are how careers end.

The check scans Python files outside tests/ directories and flags:
  - np.random.* calls (excepting allowed sampling helpers)
  - functions named *fake*, *mock*, *synthetic*, *dummy*, *stub*, *placeholder*

Allowed locations: tests/, **/tests/, test_*.py, conftest.py, notebooks/.
Allowed numpy.random functions: default_rng, permutation, RandomState, shuffle,
choice, seed (used for legitimate sampling/reproducibility, not fabrication).
Per-line bypass: append `# noqa: mock-check <reason>` to the offending line.

Usage:
    python scripts/check_no_mock_data.py <path> [<path> ...]

Exits 1 if any violation found, 0 otherwise.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SUSPICIOUS_NAME_PATTERNS = [
    "fake",
    "mock",
    "synthetic",
    "dummy",
    "stub",
    "placeholder",
]
RANDOM_API_PATTERNS = [
    ("numpy", "random"),
    ("np", "random"),
    ("random", None),
]
ALLOWED_RANDOM_FUNCTIONS = {
    "default_rng",
    "permutation",
    "RandomState",
    "shuffle",
    "choice",
    "seed",
}
TEST_PATH_FRAGMENTS = ["/tests/", "/test_", "conftest.py", "/notebooks/"]


def is_test_file(path: Path) -> bool:
    s = str(path).replace("\\", "/")
    return any(frag in s for frag in TEST_PATH_FRAGMENTS) or s.endswith("test.py")


class MockDataVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.violations: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        name_lower = node.name.lower()
        for pat in SUSPICIOUS_NAME_PATTERNS:
            if pat in name_lower and not name_lower.startswith("test_"):
                self.violations.append(
                    (
                        node.lineno,
                        f"function '{node.name}' has a suspicious name "
                        f"(contains '{pat}'); rename or move to tests/",
                    )
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        chain: list[str] = []
        cur = node.func
        while isinstance(cur, ast.Attribute):
            chain.insert(0, cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            chain.insert(0, cur.id)

        if len(chain) >= 2:
            for mod, sub in RANDOM_API_PATTERNS:
                if chain[0] == mod and (sub is None or chain[1] == sub):
                    leaf = chain[-1]
                    if leaf not in ALLOWED_RANDOM_FUNCTIONS:
                        self.violations.append(
                            (
                                node.lineno,
                                f"call to {'.'.join(chain)}() — looks like data fabrication. "
                                f"If this is legitimate sampling (LHS, MCMC init), add "
                                f"'# noqa: mock-check <reason>' on this line and prefer "
                                f"np.random.default_rng().",
                            )
                        )
        self.generic_visit(node)


def check_file(path: Path) -> list[tuple[Path, int, str]]:
    if is_test_file(path):
        return []
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as e:
        return [(path, e.lineno or 0, f"SyntaxError: {e.msg}")]

    src_lines = path.read_text().splitlines()
    visitor = MockDataVisitor(path)
    visitor.visit(tree)

    out: list[tuple[Path, int, str]] = []
    for lineno, msg in visitor.violations:
        if 1 <= lineno <= len(src_lines):
            line = src_lines[lineno - 1]
            if "noqa: mock-check" in line:
                continue
        out.append((path, lineno, msg))
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: check_no_mock_data.py <path> [<path> ...]", file=sys.stderr)
        return 2

    paths_to_scan: list[Path] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            paths_to_scan.extend(p.rglob("*.py"))
        elif p.is_file() and p.suffix == ".py":
            paths_to_scan.append(p)

    all_violations: list[tuple[Path, int, str]] = []
    for path in paths_to_scan:
        all_violations.extend(check_file(path))

    if not all_violations:
        print(f"✓ no-mock-data check passed ({len(paths_to_scan)} files scanned)")
        return 0

    print(f"✗ no-mock-data check failed: {len(all_violations)} violation(s)\n", file=sys.stderr)
    for path, lineno, msg in all_violations:
        print(f"  {path}:{lineno}: {msg}", file=sys.stderr)
    print(
        "\nIf any of these are legitimate (e.g., MCMC initialization, LHS sampling), "
        "add a `# noqa: mock-check <reason>` comment on the offending line.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
