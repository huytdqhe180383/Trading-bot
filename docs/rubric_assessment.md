# Rubric Assessment — BTC/ETH Trading Research

Assessed: 2026-05-23
Baseline rubric: `docs/rubric.md`

## Current Level: ~3.5

The codebase has strong architecture, working pipelines, and a detailed technical
audit. It falls short of Level 4 primarily on infrastructure (linter, tests
passing, file sizes) and missing documentation files.

---

## What Passes (Level 4 criteria met)

- Consistent naming conventions throughout
- Complex parts have comments (audit is thorough)
- Modular, easy-to-navigate folder structure
- 1-2 reusable utilities (`risk/risk_constraints.py`, `metrics/performance.py`)
- Clean code: DRY, small functions within files
- `ARCHITECTURE.md` present (`docs/architecture.md`)
- Extensible architecture (adapters, fusion agent)
- Solves a real user pain point (RL portfolio allocation)
- Good README with setup and usage examples

---

## What Fails (by rubric dimension)

### Code Quality (file sizes)

Rubric target: ~200 lines per module.

| File | Lines | Over By |
|---|---|---|
| `backtest.py` | 520 | 320 |
| `tradingagents_adapter.py` | 531 | 331 |
| `trading_env.py` | 503 | 303 |
| `train.py` | 355 | 155 |
| `scripts/run_live.py` | 354 | 154 |
| `metrics/performance.py` | 334 | 134 |

### Testing

- 5/10 tests fail: `ModuleNotFoundError: No module named 'pandas'` — wrong venv
  active during test run (system Python instead of `.venv`)
- `tests/__init__.py` missing
- No coverage measurement tooling (`pytest-cov` absent)
- Test cover: training hygiene, live safety, adapters, fusion, agent cost, docs,
  GPU verification, Kronos, TradingAgents (10 total)

### Linting & Formatting

- No linter configured (no `pyproject.toml`, `.flake8`, `pyproject.toml` with
  `[tool.ruff]`, or equivalent)
- No auto-formatting
- No pre-commit hooks

### Documentation

| File | Present? |
|---|---|
| `CONTRIBUTING.md` | ❌ Missing |
| `CHANGELOG.md` | ❌ Missing |
| `LICENSE` | ❌ Missing (only external Kronos has one) |
| Full docstring coverage | ❌ Partial |
| Examples / tutorials | ❌ Missing |
| API docs | ❌ Missing |

### CI/CD & Infrastructure

Rubric mentions CI/CD under Level 4→5. For a solo research project this is low
priority — running `python -m unittest discover -s tests` locally serves the
same function. No GitHub Actions workflow exists and one isn't critical.

### Version Control Hygiene

- Git history is 3 bulk-initialization commits — no incremental refactoring
  visible
- Zero git tags / releases
- No semantic versioning

### Monitoring & Security

- No structured monitoring (TensorBoard data in `logs/` is training-only)
- No alerting
- `.env` excluded from git via `.gitignore` (good)
- No secrets scanning or security policy

---

## Critical Audit Findings (from `docs/codebase_audit.md`)

These are correctness bugs, not rubric polish. They should be fixed first.

| # | Severity | Issue | File(s) |
|---|---|---|---|
| 1-F / 2-C | **Critical** | `_get_returns()` returns next candle's return — 1-hour forward leak | `trading_env.py` |
| 1-A | **Critical** | OBV normalisation lacks `.shift(1)` — look-ahead bias | `preprocess.py` |
| 1-B | **Critical** | `min_periods=1` produces distorted z-scores for first 300 candles | `preprocess.py` |
| 2-B | **High** | Flat 0.2% fee model with no maker/taker distinction | `config.py`, `trading_env.py` |
| 2-E | **High** | Softmax round-trip distortion in backtest | `backtest.py` |
| 2-F | **Low** | `REBALANCE_THRESHOLD` hardcoded in env body | `trading_env.py` |

---

## Improvement Plan

### Phase 1 — Fix Critical Bugs (correctness, not rubric)

1. Fix `_get_returns()` off-by-one — return `self._step_idx - 1` not `self._step_idx`
2. Add `.shift(1)` to OBV rolling normalisation
3. Change `min_periods=1` → `min_periods=window` in `_rolling_z_score`, drop warm-up rows
4. Add tiered maker/taker fee model + minimum order gate
5. Eliminate backtest softmax round-trip (use `step_weights` bypass)
6. Expose `REBALANCE_THRESHOLD` in `config.py`

### Phase 2 — Level 4 Gaps

7. Split `backtest.py`, `tradingagents_adapter.py`, `trading_env.py` into smaller modules (~200 lines each)
8. Add `CONTRIBUTING.md`
9. Add `tests/__init__.py`, fix test environment so all 10 pass
10. Configure linter: add `pyproject.toml` with `[tool.ruff]`

### Phase 3 — Level 4→5 Gaps

11. Add `.pre-commit-config.yaml` (ruff + isort + trailing-whitespace)
12. Add `LICENSE` (MIT or Apache 2.0)
13. Full docstring coverage on public functions
14. Add `pytest-cov` to requirements, measure baseline coverage
15. Break bulk commits into incremental refactoring history

### Phase 4 — Level 5 (Open-Source Ready)

16. Add `CHANGELOG.md` + git tags for semantic versioning
17. Write tutorial/quickstart in `docs/`
18. Add `docs/API.md`
19. Integration smoke test: `download → preprocess → train → backtest`
20. Add `examples/` directory with demo scripts

### Note on CI/CD

The rubric mentions CI/CD for Level 4→5 in a team context. For solo research:
- A local `python -m unittest` run is equivalent
- GitHub Actions would only add value if you're collaborating or want automated
  regression checks after dependency updates
- Not needed to reach Level 4; nice-to-have for Level 5

---

## 2026-05-23 Follow-Up Improvements

Implemented after this assessment:

- Added `tests/__init__.py` so the test suite is an importable package.
- Added `pyproject.toml` with a Ruff lint/format baseline.
- Added `CONTRIBUTING.md` with setup, verification, backtest, and reporting rules.
- Added an all-method ensemble comparison visualization:
  - `results/backtest_ensemble_method_comparison.csv`
  - `results/backtest_ensemble_method_comparison.png`
- Added regression coverage in `tests/test_backtest_visualization.py`.

Rechecked critical audit items against current source:

- `_get_returns()` now returns `self._returns_array[self._step_idx - 1]`.
- OBV normalization uses a shifted OBV input.
- Rolling z-score uses `min_periods=window`.
- Backtest execution uses `step_weights`, avoiding the softmax round-trip.
- `REBALANCE_THRESHOLD` is exposed in `config.py`.

Remaining high-value work:

- Split large modules, especially `backtest.py`, `tradingagents_adapter.py`, and `trading_env.py`.
- Add coverage measurement once `pytest-cov` or equivalent is accepted as a dependency.
- Add `LICENSE`, `CHANGELOG.md`, and tutorial/API docs before treating the repo as open-source ready.
