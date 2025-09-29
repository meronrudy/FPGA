# Contributing Guide

Thank you for your interest in contributing to the parameterized Q1.15 moving‑average FIR project. This guide explains the coding standards, required checks, and recommended workflows to keep contributions reliable and maintainable.

Key references:
- Linting and typing config: [pyproject.toml](pyproject.toml)
- Central logging utilities: [common/logging.py](common/logging.py)
- Import/CLI smoke check: [scripts/check_imports.py](scripts/check_imports.py)
- Simulation agent: [agents/sim.py](agents/sim.py)
- Synthesis agent: [agents/synth.py](agents/synth.py)
- Testbench and golden model: [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py), [sim/golden/fir_model.py](sim/golden/fir_model.py)

## Development standards

- Python version: 3.8+ (linters and type checker target 3.8 in [pyproject.toml](pyproject.toml))
- Linting: Use Ruff with the rules configured in [pyproject.toml](pyproject.toml)
  - The rule set includes `T20` (no print statements). Use centralized logging instead (see [common/logging.py](common/logging.py)).
- Typing: Use Mypy; add type hints to public functions and module‑level constants
- Docstrings: Provide clear, actionable docstrings for public modules/functions/classes
- Logging: Use [common/logging.py](common/logging.py); do not use `print(...)`
- File/linking in docs: Use clickable file links, for example: [agents/sim.py](agents/sim.py). Avoid linking specific functions/symbols to prevent drift.

## Pre‑PR checklist

Run these before opening a pull request:

1) Quick import/CLI smoke:
```bash
python scripts/check_imports.py
```

2) Lint and type check (see [docs/static_analysis.md](docs/static_analysis.md)):
```bash
ruff check .
mypy .
```

3) Representative simulation:
```bash
# Verilator; keep TOPLEVEL=fir8 to match the cocotb Makefile
python agents/sim.py --sim verilator --top fir8 --taps 8 --pipeline 0
```

4) Optional focused synthesis (helps validate report parsing and artifacts):
```bash
python agents/synth.py --only baseline8
```

5) Documentation updates:
- If you change parameters, flows, file locations, or CLIs, update the relevant docs:
  - README: [README.md](README.md)
  - Architecture/spec/testing/build: [docs/architecture.md](docs/architecture.md), [docs/hw_spec.md](docs/hw_spec.md), [docs/testing.md](docs/testing.md), [docs/build.md](docs/build.md)
  - CLI and configuration: [docs/cli_reference.md](docs/cli_reference.md), [docs/configuration.md](docs/configuration.md)
  - Troubleshooting/logging/static analysis: [docs/troubleshooting.md](docs/troubleshooting.md), [docs/logging_config.md](docs/logging_config.md), [docs/static_analysis.md](docs/static_analysis.md)

Tips:
- Use `LOG_LEVEL=DEBUG` while debugging local runs:
  ```bash
  LOG_LEVEL=DEBUG python agents/sim.py --sim verilator --top fir8 --taps 8
  LOG_LEVEL=DEBUG python agents/synth.py --only baseline8
  ```

## Commit messages and PRs

- Scope: Make commits focused and self‑contained
- Message style: Use descriptive titles (“synth: validate TAPS ranges in loader”) and a concise body explaining “what” and “why”
- Reference files and variants when applicable (e.g., “updates [configs/variants.yaml](configs/variants.yaml) schema comments”)
- Include links to artifacts or logs if the change affects CI outputs

## Code areas and expectations

- Simulation:
  - Make sure changes keep alignment with the cocotb Makefile defaults in [sim/cocotb/Makefile](sim/cocotb/Makefile) (e.g., `TOPLEVEL := fir8`)
  - Keep the testbench [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py) parameter‑agnostic; use environment variables and ensure coverage export logic remains intact
- Synthesis:
  - Do not break the per‑variant flow in [agents/synth.py](agents/synth.py); maintain CSV and report formats consumed by downstream tools
  - If you change constraints or top wiring, update [constraints/icebreaker.pcf](constraints/icebreaker.pcf) and relevant docs
- Configuration:
  - Be mindful of the two YAML schemas described in [docs/configuration.md](docs/configuration.md)
  - Synthesis uses nested uppercase `params`; the flat schema is for the designer/sim `--variant`
- Logging:
  - Prefer structured and concise logs; ensure agents/scripts initialize logging early (see existing patterns)

## Testing expectations

- Keep or improve coverage; tests currently enforce a threshold (see [sim/cocotb/test_fir8.py](sim/cocotb/test_fir8.py))
- Include edge cases for rounding boundaries and saturation/wrap behavior
- If you introduce handshake or latency changes, update the expected latency in tests and the documentation accordingly (e.g., [docs/hw_spec.md](docs/hw_spec.md), [docs/simulation.md](docs/simulation.md))

## CI

- The CI workflow resides in [.github/workflows/ci.yml](.github/workflows/ci.yml)
- Ensure matrix entries remain valid if you rename or add variants in [configs/variants.yaml](configs/variants.yaml)
- Reports are aggregated by [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py) into `artifacts/report_phase1.md` and `artifacts/variants_summary.csv`

## License and DCO

- All contributions are under the repository license: [LICENSE](LICENSE)
- If your organization requires a Developer Certificate of Origin (DCO), include a `Signed-off-by:` trailer as appropriate

## Getting help

- Start with [docs/troubleshooting.md](docs/troubleshooting.md)
- Open an issue with:
  - Command, logs (preferably with `LOG_LEVEL=DEBUG`)
  - Tool versions (`yosys -V`, `nextpnr-ice40 --version`, simulator version)
  - Relevant variant names from [configs/variants.yaml](configs/variants.yaml)