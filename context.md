# Under The Hood — Full Project Context (Agent Handoff)

## 1) Product Purpose
Under The Hood is a Flask web app that converts open-source tool adoption data into investor-facing intelligence.

Primary question:
- Which developer tools are actually used in real codebases, and which are strengthening or weakening?

Current product stance:
- Investor/analyst first.
- Bold interpretation voice (conclusions over raw metrics).
- Uncertainty is shown explicitly via confidence badges instead of hiding data.

## 2) Current Stack
- Python 3.9/3.11 compatible
- Web: Flask + Jinja2 templates
- Data store: SQLite (`data/uth.db`)
- Charts: Plotly
- Data/compute: numpy, pandas/scipy available
- API clients: requests + dotenv
- Deploy: Railway (`Procfile`, `railway.json`)

## 3) Repository Layout
- `scripts/`: ingestion, scoring, DB helpers, pipeline runners
- `web/`: Flask app (`app.py`, `data.py`, templates, CSS)
- `data/uth.db`: shipped snapshot DB
- `app/`: legacy Streamlit code (not used in production Flask deployment)

## 4) Phase Status (Important)
Phase 1 and Phase 2 upgrade code has been implemented and pushed to `main` in commit:
- `3cc3d1d`

### Phase 1 (mobile readability) implemented:
- Bottom mobile tab bar (`Home`, `Tools`, `Categories`, `Radar`) under 768px.
- Learn page access via mobile `?` floating link.
- Mobile-first card stacking on Home/Tool/Category/Radar/Learn.
- Category desktop table replaced with stacked cards on mobile.
- Plotly charts rendered with `responsive=True`.
- Larger mobile typography and tap targets.

### Phase 2 (downloads + confidence) implemented:
- New schema columns and migration logic for confidence/download signals.
- New script: `scripts/05_fetch_downloads.py`.
- Confidence tier + sample size + trend reliability added in score computation.
- Confidence badges added in Home, Tool Detail, Category, Radar UI.
- Tool Detail includes a new “Usage Signals” block (repo integration + registry downloads).

## 5) Data Model (Code-Level Schema)
Defined in `scripts/db.py` with `init_db()` + migration guards (`PRAGMA table_info` checks).

### Core tables:
- `tools`
- `tool_aliases`
- `tool_repos`
- `tool_snapshots`
- `categories`
- `co_installs`
- `api_cache`

### Additional existing tables:
- `repo_universe`
- `repo_manifests`
- `tool_contributors`

### New Phase 2 schema additions:

`tools` new columns:
- `usage_model` (`dependency_first` | `standalone_first` | `mixed`)
- `npm_package`
- `pypi_package`

`tool_snapshots` new columns:
- `weekly_downloads`
- `downloads_source` (`npm` | `pypi` | null)
- `sample_size`
- `confidence_tier` (`High` | `Medium` | `Low`)
- `is_trend_reliable` (1 only after enough weekly history)

New table:
- `download_snapshots`
  - unique on `(canonical_name, snapshot_date)`
  - stores weekly registry downloads per tool

## 6) Important DB State Right Now
As of current repo-local DB inspection:
- DB file: `data/uth.db`
- Size: ~25.55 MB
- `tools`: 90
- `tool_snapshots`: 227
- `tool_repos`: 9,100
- `categories`: 12
- `tool_contributors`: 470
- latest snapshot date: `2026-03-04`

Critical caveat:
- The **existing shipped DB file** still lacks newly added Phase 2 columns/tables until migration runs.
- Example currently missing in DB file before migration: `download_snapshots`, `tools.usage_model`, `tool_snapshots.confidence_tier`, etc.
- App-side code now calls `init_db()` lazily from `web/data.py` to enforce schema on first use where writable.

## 7) Pipeline

### Standard pipeline (`scripts/run_all.py`)
Order now:
1. `01_seed_tools.py`
2. `02_search_adoption.py`
3. `03_enrich_repos.py`
4. `04_compute_scores.py`
5. `05_fetch_downloads.py`
6. `06_fetch_contributors.py`

### Robust pipeline (`scripts/run_robust.py`)
- Still exists for repo-first ingestion path.
- `05_robust_repo_scrape.py` remains separate from the new `05_fetch_downloads.py`.

## 8) Scoring + Confidence Logic

### Tool metrics (per snapshot)
- `total_repos`
- `active_repos` (pushed in last 30 days)
- `new_repos_90d` (created in last 90 days)
- `stars_median`
- `enterprise_repo_count`

### Emergence score
- Growth + activity normalized by size (`log1p(total_repos)` scaling).

### Category logic
- Fragmentation index via HHI (`1 - sum(share^2)`).
- Market phase labels:
  - `Mature`
  - `Early / Competing`
  - `Consolidating`
  - `Fragmenting`
  - `In Transition`

### Confidence tier logic (`scripts/04_compute_scores.py`)
- `High`: 50+ repos and 4+ snapshots
- `Medium`: 15–49 repos OR larger base without enough history
- `Low`: under 15 repos
- Forced `Low` if metadata coverage < 60%

### Trend reliability
- `is_trend_reliable = 1` only with 4+ snapshots for that tool.

## 9) Downloads Ingestion (Phase 2)
Implemented in `scripts/05_fetch_downloads.py`.

Sources:
- npm: `api.npmjs.org/downloads/point/last-week/{package}`
- PyPI: `pypistats.org/api/packages/{package}/recent`

Behavior:
- Caches successful responses for 24h (`api_cache`).
- Caches 404/not-found for 72h to prevent hammering missing packages.
- Updates both:
  - `download_snapshots`
  - same-day/latest row in `tool_snapshots` (`weekly_downloads`, `downloads_source`)
- `standalone_first` tools skip registry signal and keep downloads as not-applicable in UI.

## 10) Flask Routes
`web/app.py`:
- `/` Home
- `/tool` Tool Deep Dive
- `/category` Category View
- `/radar` The Radar
- `/learn` How to Read This
- `/healthz`

Empty-state behavior:
- Routes guard on `db_has_data()` and render `empty.html` if no usable data.

## 11) UI Structure (Current)

### Shared base (`web/templates/base.html`)
- Desktop sidebar retained
- Mobile bottom tab bar added (<768px)
- Mobile learn shortcut (`?`) added
- Sidebar footer text now says `Updated: Weekly`

### Home (`web/templates/home.html`)
- 3 headline cards
- Movers grid with confidence badge line
- Low-confidence note shown when sample is small
- Radar banner CTA
- Category state cards
- Explainer strip

### Tool Detail (`web/templates/tool_detail.html`)
- Tool selector + hero badges
- 3 metric cards each with confidence badge
- New `Usage Signals` section (weekly downloads + code integration)
- Existing “Who’s Building This” section preserved
- Trend chart now shows “Trend building” badge/note when history is immature

### Category (`web/templates/category_view.html`)
- Category selector + 3 metric cards + insight
- Concentration chart responsive
- Desktop table includes new `Downloads` column and confidence badge near tool name
- Mobile shows stacked per-tool cards (instead of wide table)

### Radar (`web/templates/radar.html`)
- Existing route behavior preserved
- Card UI now shows confidence badge and weekly downloads line
- Builder rows retained

### Learn (`web/templates/learn.html`)
- Content intact
- Mobile readability improvements handled in CSS

### Macros
- New template macros: `web/templates/macros.html`
  - `confidence_badge(...)`
  - `trend_badge(...)`

## 12) Styling / Responsive System
Primary stylesheet:
- `web/static/styles.css`

Phase 1 additions include:
- Confidence badge styles (`.confidence-high/.medium/.low`)
- Mobile tab bar + mobile learn button
- Mobile card/table/chart behavior
- Mobile typography and tap-target sizing
- Category mobile card mode
- Radar CTA and card layout adjustments

## 13) Data Access Layer (`web/data.py`)
Now returns/downloads confidence-aware fields in:
- `get_all_tools()`
- `get_top_movers()`
- `get_tool_detail()`
- `get_radar_snapshot()`

New function:
- `get_download_history(canonical_name)` (last 12 snapshots)

Other important change:
- Lazy schema bootstrap via `init_db()` inside `_conn()` so app can self-migrate in writable environments.

## 14) Product Voice Changes
Interpretation text was updated toward stronger investor-facing conclusions:
- Category phase explanation for transition: “Something is shifting here. The current leader may not hold.”
- Tool insight text now pushes decision-oriented framing (durability, momentum, consolidation risk).

## 15) Constraints / Caveats
- Public GitHub only; private enterprise repos remain invisible.
- Dependency listing remains a proxy for usage, not guaranteed runtime utilization.
- Registry downloads include CI and mirrors; directional signal, not exact user count.
- Until migrations run on a given DB file, new Phase 2 fields/tables may be missing.
- Weekly cadence is product target; trend reliability expects multiple snapshot points.

## 16) Practical Runbook
From repo root:

```bash
cd /Users/shivambhotika/under-the-hood
python3 scripts/01_seed_tools.py
python3 scripts/02_search_adoption.py
python3 scripts/03_enrich_repos.py
python3 scripts/04_compute_scores.py
python3 scripts/05_fetch_downloads.py
python3 scripts/06_fetch_contributors.py
python3 -m flask --app web.app run --host 0.0.0.0 --port 8000
```

For robust ingestion path:

```bash
cd /Users/shivambhotika/under-the-hood
python3 scripts/run_robust.py
python3 scripts/04_compute_scores.py
python3 scripts/05_fetch_downloads.py
```

## 17) Do-Not-Touch Area (Current Collaboration Constraint)
Per current project direction:
- `/radar` route logic in `web/app.py` should not be redesigned in this stream.
- `tool_contributors` schema and contributor-collection path are owned in a separate stream.
- “Who’s Building This” content logic remains separate from the downloads/confidence stream.

## 18) Immediate Next Priorities
1. Execute Phase 2 migrations on production DB and run `05_fetch_downloads.py` so confidence/download UI is fully populated.
2. Validate mobile UX on real devices (375px and 768px) and patch edge overflows.
3. Add scheduled weekly pipeline run on Railway/GitHub Actions.
4. Add post-run validation checks (non-empty snapshot sanity, confidence coverage sanity, download ingestion sanity).

---
Context updated after Phase 1+2 implementation and push to `main` (`3cc3d1d`).
