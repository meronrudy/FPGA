# Configuration Management

This project uses YAML to define design variants and flow options, with two distinct schemas in use depending on the tool:
- Synthesis schema (nested `params` with UPPERCASE numeric keys) — used by [agents/synth.py](agents/synth.py)
- Flat schema (top‑level, human‑readable keys) — validated by [common/config.py](common/config.py) and used by [agents/designer.py](agents/designer.py) and the `--variant` path in [agents/sim.py](agents/sim.py)

Read this document carefully to avoid mixing schemas.

## Files and tools

- Primary variants file (synthesis‑oriented): [configs/variants.yaml](configs/variants.yaml)
- Loader and validator (flat schema): [common/config.py](common/config.py)
- Designer agent (YAML → normalized JSON): [agents/designer.py](agents/designer.py)
- Simulation agent (optional `--variant` via flat schema): [agents/sim.py](agents/sim.py)
- Synthesis driver (expects nested UPPERCASE `params`): [agents/synth.py](agents/synth.py)

## Synthesis schema (used by agents/synth.py)

The repository’s [configs/variants.yaml](configs/variants.yaml) is authored for the synthesis flow. Each variant:
- Has a `name`
- Has a nested `params` mapping with uppercase numeric keys
- May include optional per‑variant PnR strategy fields

Example:
```yaml
variants:
  - name: baseline8
    params: { ROUND: 1, SAT: 1, PIPELINE: 0, TAPS: 8 }

  - name: resource4
    params: { ROUND: 1, SAT: 1, PIPELINE: 0, TAPS: 4 }
    yosys_opts: "-abc9 -relut"
    nextpnr_opts: "--placer heap --router router2"
    seed: 1
```

Enforced by [agents/synth.py](agents/synth.py):
- Allowed TAPS: {4, 8, 16, 32}
- Allowed PIPELINE/ROUND/SAT: {0, 1}
- Optional hooks: `yosys_opts`, `nextpnr_opts`, `seed` (if present, must be valid types)

## Flat schema (used by common/config.py, designer, and sim --variant)

The flat schema is validated by [common/config.py](common/config.py) and consumed by:
- [agents/designer.py](agents/designer.py)
- [agents/sim.py](agents/sim.py) when you pass `--variant` (because it calls the flat‑schema loader)

Fields per variant (flat):
- Required
  - name: string
  - taps: integer (positive)
- Optional
  - pipeline: int or bool (non‑negative; typically 0 or 1)
  - round: string — one of "round" or "truncate"
  - sat: string — one of "saturate" or "wrap"
  - seed: int
  - yosys_opts: string
  - nextpnr_opts: string
  - freq: int (MHz, informational)

Example (flat):
```yaml
variants:
  - name: baseline8
    taps: 8
    pipeline: 0
    round: "round"
    sat: "saturate"
    # optional:
    yosys_opts: ""
    nextpnr_opts: ""
    seed: 1
    freq: 12
```

Notes:
- The flat schema prioritizes readability and semantic keys ("round"/"truncate", "saturate"/"wrap").
- Range constraints like TAPS ∈ {4,8,16,32} are enforced downstream by specific tools (e.g., [agents/synth.py](agents/synth.py) or runtime checks in [agents/sim.py](agents/sim.py)).

## Which schema should I use?

- For synthesis/PnR with [agents/synth.py](agents/synth.py): keep using the repository’s synthesis schema in [configs/variants.yaml](configs/variants.yaml).
- For the simulation agent’s `--variant` feature or designer JSON export:
  - Provide a separate flat‑schema YAML, or
  - Prefer explicit CLI overrides to avoid schema mismatch, for example:
    ```bash
    python agents/sim.py --sim verilator --top fir8 --taps 8 --pipeline 0 --round round --sat saturate
    ```
  - If you choose to maintain a second YAML for flat schema (e.g., `configs/variants_flat.yaml`), point the tools to it explicitly.

## Designer agent: emitting normalized JSON

The designer agent reads a flat‑schema YAML via [common/config.py](common/config.py) and writes normalized JSON for downstream workflows.

Example:
```bash
# Using a flat-schema YAML (do not point this at the synthesis-style variants.yaml)
python -m agents.designer --input configs/variants_flat.yaml --output artifacts/variants.json -v
```

- Output file: `artifacts/variants.json`
- Exit codes (from [agents/designer.py](agents/designer.py)):
  - 0 success
  - 2 file not found or YAML parse error
  - 3 schema validation error (flat schema)
  - 4 write/permission error
  - 1 unexpected error

## Validation behaviors and error reporting

- Flat schema validator in [common/config.py](common/config.py):
  - Ensures each `variant` is a mapping with required `name` (non‑empty string) and `taps` (int).
  - Type checks optional fields (`pipeline` int/bool, `round`/`sat` strings, etc.).
  - Raises `ConfigError` with a descriptive message on failure.

- Synthesis schema checks in [agents/synth.py](agents/synth.py):
  - Confirms nested `params` exist for each variant with numeric UPPERCASE keys.
  - Normalizes types to integers and enforces allowed sets.
  - Exits with clear errors when a variant is unknown (via `--only`) or a param is invalid.

- Simulation agent [agents/sim.py](agents/sim.py):
  - When `--variant` is used, it attempts to load a flat‑schema YAML via [common/config.py](common/config.py).
  - Then merges CLI overrides and validates:
    - `taps` positive integer
    - `pipeline` non‑negative integer
    - `round` ∈ {"round","truncate"}
    - `sat` ∈ {"saturate","wrap"}
  - Returns exit codes:
    - 0 success
    - 2 file not found or YAML parse error
    - 3 configuration/validation error
    - 4 subprocess failure (Make returned non‑zero)
    - 1 unexpected error

## Typical mistakes and how to avoid them

- Mixing schemas:
  - Symptom: `--variant` on [agents/sim.py](agents/sim.py) fails to find the variant or complains about types.
  - Fix: Use a flat‑schema YAML for `--variant` or pass explicit overrides (`--taps/--pipeline/--round/--sat`).

- Type mismatches:
  - Flat schema expects `round`/`sat` as human‑readable strings, not integers. Use `"round"`/`"truncate"`, `"saturate"`/`"wrap"`.

- Missing required keys:
  - Both schemas require `name`; flat schema also requires `taps`.

- Invalid ranges:
  - Synthesis flow enforces TAPS ∈ {4,8,16,32} and binary values for PIPELINE/ROUND/SAT. Correct the YAML to match these sets.

- Case sensitivity:
  - Synthesis schema keys inside `params` are UPPERCASE numeric.
  - Flat schema uses lowercase semantic keys with string values for `round` and `sat`.

## Recommendations

- Continue using the provided [configs/variants.yaml](configs/variants.yaml) for synthesis.
- For simulation variants or the designer export, maintain a separate flat‑schema YAML (e.g., `configs/variants_flat.yaml`), or rely on explicit CLI flags with [agents/sim.py](agents/sim.py).
- Add JSON exports to CI if you adopt the designer workflow; keep artifacts under `artifacts/`.

## Related documentation

- Simulation guide: [docs/simulation.md](docs/simulation.md)
- Synthesis flow: [docs/synthesis.md](docs/synthesis.md)
- Build system and artifacts: [docs/build.md](docs/build.md)
- Logging configuration: [docs/logging_config.md](docs/logging_config.md)