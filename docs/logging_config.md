# Logging Configuration

Centralized logging is provided by [common/logging.py](common/logging.py). All agents and scripts initialize logging at entry and honor an environment variable `LOG_LEVEL` as well as optional CLI verbosity flags.

Policy:
- Use the shared logger utilities; avoid `print(...)`. The linter forbids prints via Ruff rule T20 (see [pyproject.toml](pyproject.toml)).
- Prefer structured, concise logs with clear prefixes (the utilities include module names).

## Where logging is initialized

- Simulation agent: [agents/sim.py](agents/sim.py)
- Synthesis agent: [agents/synth.py](agents/synth.py)
- Designer agent: [agents/designer.py](agents/designer.py)
- Report generator: [scripts/mk_phase1_report.py](scripts/mk_phase1_report.py)
- Report parser: [scripts/parse_nextpnr_report.py](scripts/parse_nextpnr_report.py)
- Import smoke: [scripts/check_imports.py](scripts/check_imports.py)

All of the above import and call helpers from [common/logging.py](common/logging.py).

## Controls

Environment variable:
- `LOG_LEVEL` accepted names: `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, `NOTSET`
- Example:
  ```bash
  LOG_LEVEL=DEBUG python agents/synth.py --only baseline8
  LOG_LEVEL=INFO  python scripts/parse_nextpnr_report.py build/baseline8
  ```

CLI verbosity (where supported):
- Many agents also expose `-v/--verbose` flags that map to:
  - `-v` → INFO
  - `-vv` → DEBUG
- Explicit `--log-level` overrides both `LOG_LEVEL` and `-v`.

Examples using the simulation agent [agents/sim.py](agents/sim.py):
```bash
# INFO via -v
python agents/sim.py -v --sim verilator --top fir8 --taps 8

# DEBUG via -vv
python agents/sim.py -vv --sim icarus --top fir8 --taps 16

# Explicit level overrides everything
python agents/sim.py --log-level DEBUG --sim verilator --top fir8 --taps 8
```

## Formatting and behavior

The root logger is configured by [common/logging.py](common/logging.py) with:
- Timestamped format: `%(asctime)s %(levelname)-8s %(name)s: %(message)s`
- Output to stderr (suitable for CI)
- Handler deduplication to prevent duplicate logs on re-initialization

Helpers:
- `setup_logging(level=None, ...)` — configure root logging, using `LOG_LEVEL` when `level` is not provided
- `get_logger(__name__)` — module logger
- `set_verbosity(count)` — map `-v` counts to levels (WARNING/INFO/DEBUG)

## No print statements

Rationale:
- Consistent formatting and CI-friendly output
- Central control of verbosity across all tools

Enforcement:
- See Ruff configuration in [pyproject.toml](pyproject.toml) selecting rule set `T20` (flake8-print), which flags `print(...)`.

## Troubleshooting

- If no logs appear, ensure `LOG_LEVEL` or `-v` is set and that the tool you are running initializes logging (listed above).
- In CI or scripted runs, prefer `LOG_LEVEL=DEBUG` during diagnosis:
  ```bash
  LOG_LEVEL=DEBUG python agents/synth.py