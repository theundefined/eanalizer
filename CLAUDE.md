# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`eanalizer` is a Python CLI for analyzing home energy consumption/production data exported from the Enea utility (Poland). It calculates costs across tariffs (G11, G12, G12w), simulates net-metering and physical battery storage, and can correlate consumption with real hourly market prices (RCE) from the PSE API. A companion tool, `enea-downloader`, logs into the Enea eBOK web portal and downloads the source CSVs automatically.

## Commands

Always invoke the app through the wrapper scripts, never `python -m ...` directly — they auto-create `.venv` and install the package in editable mode on first run, and this is also the convention used in docs/examples:

```bash
./eanalizer-cli --taryfa G12w --z-netmetering
./enea-downloader-cli --report
```

Run the test suite (must be run after every code/config change, per project convention):

```bash
.venv/bin/python -m unittest discover tests
```

Run a single test module or test case:

```bash
.venv/bin/python -m unittest tests.test_core
.venv/bin/python -m unittest tests.test_core.TestCoreFunctionality.test_some_case
```

Lint (as run in CI):

```bash
ruff check .
```

Update translations (after adding/changing any user-facing `_(...)` string in `cli.py`):

```bash
./update_translations.sh
python scripts/translate.py   # apply automatic translations from the dictionary
# then manually review locales/pl/LC_MESSAGES/eanalizer.po for anything untranslated
```

## Architecture

- **Entry points** (`pyproject.toml` `[project.scripts]`): `eanalizer.cli:main` and `eanalizer.downloader_cli:main`. The shell wrappers `eanalizer-cli` / `enea-downloader-cli` bootstrap `.venv` and call these.
- **`eanalizer/cli.py`** — argparse CLI, i18n setup (gettext, `.mo` files under `locales/`), orchestrates: load config → load & sort CSV data → filter by date range → dispatch to one of three analysis modes (RCE analysis, tariff comparison, or single full analysis) → optional CSV exports.
- **`eanalizer/core.py`** — all analysis/simulation logic, operating on plain functions rather than classes:
  - `run_full_analysis`: the central hourly simulation loop. For each hour it nets production against consumption, charges/discharges a virtual "storage" (capacity 0 = no storage, so this same function handles both the plain-tariff and physical-battery-simulation cases), and accumulates per-tariff-zone stats via `TariffManager`.
  - Net-metering cost calculation is a *separate* pass over the zone stats after the hourly loop: zones are processed sorted by price descending, with unused credit rolling over from more expensive to cheaper zones (cascade logic — see `AIDEV_GUIDELINES.md` intent).
  - `run_tariff_comparison` calls `run_full_analysis` once per tariff and ranks results.
  - `run_rce_analysis` is a separate, simpler cost model driven by real hourly market prices instead of tariff zones.
  - Other functions: date filtering, daily aggregation, missing-hour detection, optimal-battery-capacity calculation (max of "cover net-export days" vs "cover peak-zone arbitrage" capacity), CSV export.
- **`eanalizer/tariffs.py`** (`TariffManager`) — reads zone/price rules from a CSV (`tariff, zone_name, day_type, start_hour, end_hour, energy_price, dist_price, dist_fee`), resolves the zone+price for a given timestamp using `holidays.Poland()` for weekend/holiday detection, and handles overnight zones (start_hour > end_hour).
- **`eanalizer/data_loader.py`** — parses Enea's quirky CSV export format (BOM, null bytes, `="..."`-wrapped timestamps, comma decimals, both pre- and post-balancing volume columns) into `EnergyData` records.
- **`eanalizer/models.py`** — two `@dataclass`es: `EnergyData` (raw hourly import/export volumes) and `SimulationResult` (hourly simulation output incl. storage state).
- **`eanalizer/price_fetcher.py`** — fetches/caches hourly RCE prices from the PSE API (`api.raporty.pse.pl`) as one JSON file per day under the cache dir; resamples 15-min data to hourly means.
- **`eanalizer/config.py`** (`AppConfig`) — resolves config/data/cache directories. When run from a dev checkout (a `pyproject.toml` is present in cwd) it defaults to `./config`, `./data`, `./cache`; otherwise it uses `platformdirs` OS-standard locations. Interactively prompts for and persists these paths plus Enea credentials in `config.ini` on first run. Also seeds a default `tariffs.csv` (2026 ENEA Operator gross prices) if none exists.
- **`eanalizer/downloader.py`** (`EneaDownloader`) / **`downloader_cli.py`** — logs into `ebok.enea.pl` (scrapes a CSRF token, follows the multi-client selection flow), downloads one CSV per available year, and skips re-downloading current-year data less than an hour old unless `--force` is passed. `--report`/`-r` only reports the on-disk data range without downloading.

## Data flow

CSV files (manually downloaded from Enea eBOK or fetched via `enea-downloader-cli`) → `data_loader.load_from_enea_csv` → sorted list of `EnergyData` → optional date filter → `TariffManager` for pricing → `core.py` analysis functions → console summary + optional CSV exports (hourly simulation and/or daily aggregates).

## i18n

CLI strings are wrapped in `_()` (gettext) in `cli.py`; translations live in `locales/pl/`. `.pot`/`.po` files are regenerated with `update_translations.sh`, which shells out to `pybabel` (extraction config in `babel.cfg`) and then `scripts/translate.py` for automated translation lookups.

## Conventions to follow (from `AIDEV_GUIDELINES.md`)

- Every functional code change needs a corresponding unit test — add one for new behavior, update the existing one for modified behavior. Never delete a test unless the feature it covers was intentionally removed.
- Any CLI flag addition/removal/rename must be reflected immediately in `README.md` (examples and the options table).
- Run the full test suite after every code or config change.
- After renaming/moving a function, check and fix every import that referenced it.
- Always reference the wrapper scripts (`./eanalizer-cli`, `./enea-downloader-cli`) in docs and examples, not direct module invocation.
