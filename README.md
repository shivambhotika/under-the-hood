# Under The Hood

> What developer tools are actually being used in real codebases — and are they growing or dying?

Under The Hood scans GitHub repositories and reads dependency files to measure real tool adoption.
Not surveys. Not social media. What's literally installed in the code.

## Stack

- Python 3.11+
- Flask web app
- SQLite database (`data/uth.db`)
- Plotly charts
- GitHub API + caching

## Local Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Create env file:
   ```bash
   cp .env.example .env
   ```
3. Add your token in `.env`:
   ```env
   GITHUB_TOKEN=ghp_your_token_here
   ```

## Build Data

Standard pipeline (tool-first, slower for large coverage):

```bash
python scripts/run_all.py
```

Robust pipeline (repo-first, recommended for bigger datasets):

```bash
python scripts/run_robust.py
```

Optional tuning for robust pipeline:

```bash
DISCOVERY_PAGES=8 REPO_SCAN_LIMIT=12000 python scripts/05_robust_repo_scrape.py
```

Or run scripts one by one:

```bash
python scripts/01_seed_tools.py
python scripts/02_search_adoption.py
python scripts/03_enrich_repos.py
python scripts/04_compute_scores.py
python scripts/05_robust_repo_scrape.py
```

## Run Web App Locally

```bash
flask --app web.app run --host 0.0.0.0 --port 8000
```

Then open: `http://localhost:8000`

## Deploy to Railway

1. Push this repo to GitHub.
2. In Railway, create a new project from that GitHub repo.
3. Add env var in Railway project settings:
   - `GITHUB_TOKEN` = your GitHub PAT
4. Deploy. Railway will use `Procfile` / `railway.json` start command automatically.
5. Open the Railway URL.

## Notes

- Data is built from public GitHub repositories.
- 500+ star filtering is used to focus on serious maintained projects.
- Tool counts are resume-safe and deduplicated by DB constraints.
