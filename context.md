# Under The Hood — Full Project Context (Agent Handoff)

## 1) Project Purpose
Under The Hood is a Python web app that tracks real open-source tool adoption from GitHub dependency manifests and turns it into plain-English market intelligence.

Primary question:
- "What developer tools are actually being used in real codebases, and are they growing or dying?"

Current positioning in code:
- Flask web app with dark themed UI and plain-English explainer language.
- SQLite-backed local snapshot analytics.
- Pipeline scripts that gather, enrich, and score tool adoption signals.

## 2) Current Tech Stack
- Python 3.9/3.11 compatible codebase
- Web: Flask + Jinja templates
- Data store: SQLite (`data/uth.db`)
- Charts: Plotly
- Data libs: numpy, pandas/scipy available in requirements
- API client: requests + dotenv
- Deployment: Railway via `Procfile` / `railway.json`

## 3) Repository Layout
- `scripts/` data pipeline and DB modules
- `web/` Flask app (`app.py`, `data.py`, templates, CSS)
- `data/uth.db` current shipped production snapshot
- `app/` old Streamlit code still present but not used by current deploy path

## 4) Data Model (Actual Schema in `scripts/db.py`)
Core analytics tables:
- `tools`: canonical tool universe
- `tool_aliases`: alias -> canonical mapping
- `tool_repos`: per-tool per-repo usage records (unique by canonical + repo)
- `tool_snapshots`: daily per-tool aggregates
- `categories`: per-category computed aggregates and insights
- `co_installs`: reserved table for co-install analysis (currently not populated)
- `api_cache`: JSON API cache

Extended robust-scrape tables in schema:
- `repo_universe`: discovered repo universe
- `repo_manifests`: cached manifest contents

Important current DB state:
- Current shipped `data/uth.db` was slimmed for GitHub size limits, and currently does **not** contain `repo_universe` / `repo_manifests` tables (they are in schema code, but not present in this shipped DB file).

## 5) Tool Universe and Categories
Seeded tool universe (`scripts/01_seed_tools.py`):
- 47 tools
- 9 categories:
  - `AI/ML`
  - `API Framework`
  - `Bundler`
  - `Linting`
  - `ORM`
  - `Package Manager`
  - `State Management`
  - `Testing`
  - `UI Components`

Ecosystems tracked:
- `npm`, `pypi`, (schema supports `cargo`, `go`)

## 6) Pipeline Options

### A) Standard Pipeline (Tool-First)
Entry: `scripts/run_all.py`
1. `01_seed_tools.py` (idempotent seed)
2. `02_search_adoption.py` (GitHub code search by tool + manifest)
3. `03_enrich_repos.py` (repo metadata enrich)
4. `04_compute_scores.py` (snapshots + categories)

### B) Robust Pipeline (Repo-First)
Entry: `scripts/run_robust.py`
1. `01_seed_tools.py`
2. `05_robust_repo_scrape.py`
3. `04_compute_scores.py`

Robust approach details (`05_robust_repo_scrape.py`):
- Discovers repos via `search/repositories` by language + star bucket
- Pulls manifest contents (`package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod`)
- Parses manifests locally and maps dependencies to canonical tools
- Upserts into `tool_repos`

## 7) Key Calculations and Logic

### 7.1 Tool-level metrics (`02` and `04`)
For each tool/day snapshot:
- `total_repos`: count distinct repos using tool
- `active_repos`: repos with `pushed_at` in last 30 days
- `new_repos_90d`: repos with `created_at` in last 90 days
- `stars_median`: median stars across repos

Current code uses cleaned rows only:
- filters on `stars > 0` for snapshot metrics

### 7.2 Emergence score
Formula:
```python
recency_ratio = new_repos_90d / max(1, total_repos)
activity_ratio = active_repos / max(1, total_repos)
size_log = log1p(total_repos)
score = (recency_ratio*0.5 + activity_ratio*0.3) * size_log * 10
score = min(score, 100)
```
Interpretation:
- Higher = faster growth from meaningful active base

### 7.3 Category fragmentation (HHI-based)
```python
shares = [tool_count/total for tool_count in category]
hhi = sum(s**2 for s in shares)
fragmentation_index = 1 - hhi
```
- 1.0 = highly fragmented
- 0.0 = single-tool concentration

### 7.4 Market phase logic
`market_phase(frag_index, top_share_pct, avg_emergence)` returns:
- `Mature`
- `Early / Competing`
- `Consolidating`
- `Fragmenting`
- `In Transition`

### 7.5 Deterministic insight text
Category insight sentences are generated from phase + leader/runner-up + emergence context (no LLM).

### 7.6 UI signal labels (`web/data.py`)
- `Dominant`
- `Breakout`
- `Rising`
- `Fading`
- `Stable`
- `Active`

## 8) Current Live Data Snapshot (from `data/uth.db`)
Snapshot date:
- `2026-03-03`

Dataset size:
- `tools`: 47
- `categories`: 9
- `tool_snapshots` rows for snapshot date: 47
- `tool_repos`: 9,100
- distinct repos represented in `tool_repos`: 3,164
- verified rows (`stars > 0`): 9,100
- unknown rows (`stars = 0`): 0
- filtered rows (`stars = -1`): 0
- `api_cache` rows: 0

Home summary values currently shown:
- total repos tracked (sum of per-tool totals): 8,950
- total tools tracked: 47
- total categories: 9
- biggest mover: ESLint

Top 6 movers (current):
1. ESLint (Linting) — 1,670 repos, emergence 22.62
2. Prettier (Linting) — 1,376 repos, emergence 21.99
3. Vitest (Testing) — 603 repos, emergence 20.85
4. Vite (Bundler) — 411 repos, emergence 19.76
5. Jest (Testing) — 550 repos, emergence 18.96
6. esbuild (Bundler) — 311 repos, emergence 18.17

Category leaders and shares (current):
- AI/ML: OpenAI SDK (42.18%), runner-up Transformers (22.64%), phase: In Transition
- API Framework: Express (43.82%), runner-up FastAPI (24.12%), phase: In Transition
- Bundler: Vite (24.48%), runner-up webpack (22.22%), phase: In Transition
- Linting: ESLint (47.81%), runner-up Prettier (39.39%), phase: In Transition
- ORM: SQLAlchemy (51.08%), runner-up Drizzle (19.05%), phase: In Transition
- Package Manager: uv (44.87%), runner-up pnpm (42.31%), phase: In Transition
- State Management: Zustand (44.04%), runner-up Redux Toolkit (36.24%), phase: In Transition
- Testing: Vitest (32.04%), runner-up Jest (29.22%), phase: In Transition
- UI Components: Material UI (40.00%), runner-up Ant Design (35.00%), phase: Fragmenting

Current generated category insights:
- 8 categories currently produce "In transition" style insight text.
- UI Components currently produces a "Fragmenting" insight.

## 9) Web App Behavior (Flask)
Entry:
- `web/app.py`

Routes:
- `/` Home
- `/tool` Tool deep dive
- `/category` Category intelligence
- `/learn` Plain-English glossary
- `/healthz` health endpoint

Empty-state guard:
- All routes call `db_has_data()` through route logic and render `empty.html` if no data.

Caching:
- `web/data.py` uses in-process TTL cache wrappers:
  - `db_has_data`: 60s
  - most other query functions: 900s
- Restarting Flask clears cache.

### Home page (`web/templates/home.html`)
Sections:
- Hero and summary sentence
- 3 headline cards
- Top movers cards (6)
- Category state cards
- Explainer strip

### Tool page (`web/templates/tool_detail.html`)
Sections:
- Tool selector
- Tool hero (name/description/badges/github)
- 3 key metric cards
- "What this means" insight box
- Version spread chart (horizontal bars)
- Top repos list
- Adoption trend chart (line, if history >1)

### Category page (`web/templates/category_view.html`)
Sections:
- Category selector + header
- 3 metric cards
- Category insight box
- Horizontal concentration bar chart
- comparison table with signal coloring

### Learn page (`web/templates/learn.html`)
- Full non-technical explainer content with collapsible key concepts.

## 10) Charting and UI Logic
All Plotly charts use dark theme defaults from `web/app.py`:
- `paper_bgcolor = #09090B`
- `plot_bgcolor = #0F0F12`
- IBM Plex Mono font

Charts in app:
- Tool page version spread: horizontal bar
- Tool page adoption over time: line+markers
- Category page concentration: horizontal bar

Main comparison table (category page):
- HTML table, row color by signal:
  - green: rising/breakout
  - red: fading
  - default otherwise

## 11) Runtime/Deploy
Local run:
```bash
python3 -m flask --app web.app run --host 0.0.0.0 --port 8000
```

Railway startup:
- `Procfile`: `gunicorn web.app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
- `railway.json` mirrors start command

Critical env var:
- `GITHUB_TOKEN`

## 12) Known Constraints and Caveats
1. Data source = public GitHub only; private enterprise repos are not covered.
2. Dependency-file presence is proxy for usage, not guaranteed runtime use.
3. Snapshot trend can look "flat" if no fresh ingestion runs are executed.
4. Current category mix includes engineering-heavy categories (Linting/Bundler/Testing), which can reduce non-technical clarity.
5. `app/` Streamlit code still exists but is not part of current Flask deploy path.
6. Robust schema tables may be absent in slimmed production DB until `init_db()` runs with latest schema and robust script populates them.

## 13) Practical Runbooks

### Refresh data quickly (standard)
```bash
python3 scripts/02_search_adoption.py
python3 scripts/03_enrich_repos.py
python3 scripts/04_compute_scores.py
```

### Run robust collection
```bash
DISCOVERY_PAGES=6 REPO_SCAN_LIMIT=8000 python3 scripts/05_robust_repo_scrape.py
python3 scripts/04_compute_scores.py
```

### Full robust pipeline
```bash
python3 scripts/run_robust.py
```

## 14) Suggested Next Agent Priorities
1. Product clarity pass:
- create non-technical default mode
- hide low-business-impact categories by default
- make headline sections decision-first (not metric-first)

2. Data quality/confidence layer:
- expose confidence badges tied to sample size and freshness
- explicitly communicate directional vs high-confidence signals

3. Operational resilience:
- add periodic scheduled pipeline runs
- add automated post-run validation checks for non-zero snapshot sanity and category consistency

4. Optional schema cleanup migration:
- ensure `repo_universe` / `repo_manifests` tables exist in deployed DB and are used consistently if robust pipeline becomes default.

---
Last updated in this context file based on project state and DB snapshot date `2026-03-03`.
