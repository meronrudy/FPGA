# Static Analysis and Type Checking

This project uses Ruff and Mypy to enforce code quality and basic type safety across Python tooling and agents.

Configuration:
- Tooling versions/targets are declared in [pyproject.toml](pyproject.toml)
  - Ruff target version: Python 3.8
  - Mypy python_version: 3.8
  - Exclusions: `build/`, `artifacts/`, and `sim/cocotb/` trees are excluded from type checking and linting to avoid vendor/build noise

Python version requirement:
- Ensure Python 3.8+ is available in your environment. The linters are configured to reason about 3.8 semantics.

Install dependencies:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Ruff

Ruff is configured as the linter (and optional fixer) using the ruleset specified in [pyproject.toml](pyproject.toml). Key points:
- Target version: `py38`
- Selected rules include pycodestyle/pyflakes, isort, pyupgrade, pep8-naming, bugbear, flake8-* families, and `T20` to forbid print statements (use logging instead; see [common/logging.py](common/logging.py))
- Exclusions: `build`, `artifacts`, and `__pycache__` directories

Common commands:
```bash
# Lint the repository
ruff check .

# Attempt to auto-fix what can be fixed safely
ruff check . --fix
```

Typical issues flagged:
- Unused imports/variables
- Import ordering (isort)
- PyUpgrade suggestions (modern syntax)
- Print statements (use central logging utilities)
- Naming and common bug patterns (flake8-naming, bugbear)

## Mypy

Mypy is configured with Python 3.8, strict optional checks, and several warnings enabled. The `sim/cocotb` subtree and build/artifact directories are excluded to avoid simulator/VPI-specific modules.

Run:
```bash
mypy .
```

Behavior (see [pyproject.toml](pyproject.toml)):
- `ignore_missing_imports = true` to avoid blocking on simulator/vendor modules
- `strict_optional = true`, `warn_return_any = true`, `warn_unused_ignores = true`
- `exclude = "(^build/|^artifacts/|^sim/cocotb/)"`

Tips:
- Prefer explicit types for public function signatures and module-level constants.
- Use `from __future__ import annotations` to reduce forward-reference verbosity (already used in agents/scripts).
- Where third-party libraries are untyped, wrap imports in narrow modules or add local `# type: ignore[import]` with justification.

## Pre-PR checklist

Before raising a PR:
```bash
# 1) Quick import and CLI smoke
python scripts/check_imports.py

# 2) Lint and type-check
ruff check .
mypy .
```

If you intentionally skip certain subtrees (e.g., experimental scripts), add/justify exclusions in [pyproject.toml](pyproject.toml) rather than suppressing inline.

## Troubleshooting

- If Ruff/Mypy are not found, verify they are installed via [requirements.txt](requirements.txt).
- For persistent third-party typing gaps, consider local `py.typed` stubs or relax `ignore_missing_imports` selectively.
- If output is too quiet/noisy, control verbosity of project tools via logging: see [docs/logging_config.md](docs/logging_config.md).