from __future__ import annotations

import argparse
from collections import Counter
from urllib.parse import quote

import requests

try:
    from scripts.db import get_conn, init_db
except ModuleNotFoundError:
    from db import get_conn, init_db

SEED_TOOLS = [
    # Testing
    ("vitest", "Vitest", "npm", "Testing", "Fast test runner built for Vite-based projects", "vitest-dev/vitest"),
    ("jest", "Jest", "npm", "Testing", "The most widely used JavaScript testing framework", "jestjs/jest"),
    ("playwright", "Playwright", "npm", "Testing", "Browser automation and end-to-end testing by Microsoft", "microsoft/playwright"),
    ("pytest", "pytest", "pypi", "Testing", "The standard testing framework for Python", "pytest-dev/pytest"),
    ("mocha", "Mocha", "npm", "Testing", "Flexible JavaScript test framework, older generation", "mochajs/mocha"),

    # ORM / Database
    ("drizzle-orm", "Drizzle", "npm", "ORM", "Modern TypeScript ORM with a SQL-first approach", "drizzle-team/drizzle-orm"),
    ("prisma", "Prisma", "npm", "ORM", "Popular Node.js ORM with auto-generated types", "prisma/prisma"),
    ("typeorm", "TypeORM", "npm", "ORM", "ORM for TypeScript and JavaScript, older generation", "typeorm/typeorm"),
    ("sequelize", "Sequelize", "npm", "ORM", "Promise-based Node.js ORM, the original", "sequelize/sequelize"),
    ("sqlalchemy", "SQLAlchemy", "pypi", "ORM", "The standard Python SQL toolkit and ORM", "sqlalchemy/sqlalchemy"),
    ("sqlmodel", "SQLModel", "pypi", "ORM", "Modern Python ORM built on SQLAlchemy and Pydantic", "tiangolo/sqlmodel"),

    # Linting / Formatting
    ("ruff", "Ruff", "pypi", "Linting", "Extremely fast Python linter written in Rust", "astral-sh/ruff"),
    ("flake8", "Flake8", "pypi", "Linting", "Classic Python style guide checker", "PyCQA/flake8"),
    ("pylint", "Pylint", "pypi", "Linting", "Comprehensive Python code analysis tool", "pylint-dev/pylint"),
    ("black", "Black", "pypi", "Linting", "Opinionated Python code formatter", "psf/black"),
    ("eslint", "ESLint", "npm", "Linting", "Pluggable linting tool for JavaScript", "eslint/eslint"),
    ("prettier", "Prettier", "npm", "Linting", "Opinionated code formatter for JavaScript/TypeScript", "prettier/prettier"),
    ("biome", "@biomejs/biome", "npm", "Linting", "Fast formatter and linter, Rust-based replacement", "biomejs/biome"),

    # Package managers
    ("pnpm", "pnpm", "npm", "Package Manager", "Fast, disk-efficient package manager for Node.js", "pnpm/pnpm"),
    ("uv", "uv", "pypi", "Package Manager", "Extremely fast Python package manager written in Rust", "astral-sh/uv"),
    ("poetry", "Poetry", "pypi", "Package Manager", "Dependency management and packaging tool for Python", "python-poetry/poetry"),

    # API frameworks
    ("fastapi", "FastAPI", "pypi", "API Framework", "Modern, fast Python web framework for building APIs", "tiangolo/fastapi"),
    ("flask", "Flask", "pypi", "API Framework", "Lightweight Python web framework, the classic", "pallets/flask"),
    ("django", "Django", "pypi", "API Framework", "High-level Python web framework with batteries included", "django/django"),
    ("express", "Express", "npm", "API Framework", "Minimal Node.js web framework, the original", "expressjs/express"),
    ("hono", "Hono", "npm", "API Framework", "Ultra-fast web framework for edge environments", "honojs/hono"),
    ("fastify", "Fastify", "npm", "API Framework", "High-performance Node.js web framework", "fastify/fastify"),

    # UI components
    ("shadcn-ui", "shadcn/ui", "npm", "UI Components", "Copy-paste component library built on Radix UI", "shadcn-ui/ui"),
    ("@mui/material", "Material UI", "npm", "UI Components", "React components implementing Google Material Design", "mui/material-ui"),
    ("@chakra-ui/react", "Chakra UI", "npm", "UI Components", "Accessible, themeable React component library", "chakra-ui/chakra-ui"),
    ("antd", "Ant Design", "npm", "UI Components", "Enterprise-grade React UI component library", "ant-design/ant-design"),

    # Bundlers / build tools
    ("vite", "Vite", "npm", "Bundler", "Fast modern build tool and dev server", "vitejs/vite"),
    ("webpack", "webpack", "npm", "Bundler", "The original and most widely used JavaScript bundler", "webpack/webpack"),
    ("esbuild", "esbuild", "npm", "Bundler", "Extremely fast JavaScript bundler written in Go", "evanw/esbuild"),
    ("rollup", "Rollup", "npm", "Bundler", "Module bundler focused on ES modules and libraries", "rollup/rollup"),
    ("turbo", "Turborepo", "npm", "Bundler", "High-performance build system for JavaScript monorepos", "vercel/turbo"),

    # State management
    ("zustand", "Zustand", "npm", "State Management", "Minimal state management for React", "pmndrs/zustand"),
    ("@reduxjs/toolkit", "Redux Toolkit", "npm", "State Management", "The official, modern way to use Redux", "reduxjs/redux-toolkit"),
    ("jotai", "Jotai", "npm", "State Management", "Primitive and flexible state for React", "pmndrs/jotai"),
    ("mobx", "MobX", "npm", "State Management", "Simple, scalable state management", "mobxjs/mobx"),

    # AI / ML
    ("langchain", "LangChain", "pypi", "AI/ML", "Framework for building LLM-powered applications", "langchain-ai/langchain"),
    ("openai", "OpenAI SDK", "pypi", "AI/ML", "Official Python client for the OpenAI API", "openai/openai-python"),
    ("anthropic", "Anthropic SDK", "pypi", "AI/ML", "Official Python client for the Anthropic API", "anthropics/anthropic-sdk-python"),
    ("transformers", "Transformers", "pypi", "AI/ML", "HuggingFace library for pretrained models", "huggingface/transformers"),
    ("pydantic-ai", "PydanticAI", "pypi", "AI/ML", "Agent framework built on Pydantic by the Pydantic team", "pydantic/pydantic-ai"),
    ("litellm", "LiteLLM", "pypi", "AI/ML", "Call any LLM API with one unified interface", "BerriAI/litellm"),
    ("llama-index", "LlamaIndex", "pypi", "AI/ML", "Data framework for LLM-based applications", "run-llama/llama_index"),

    # Testing additions
    ("cypress", "Cypress", "npm", "Testing", "E2E testing pioneer, losing ground to Playwright in new projects", "cypress-io/cypress"),
    ("pytest-asyncio", "pytest-asyncio", "pypi", "Testing", "Async test support, standard for FastAPI and async Python apps", "pytest-dev/pytest-asyncio"),
    ("ava", "AVA", "npm", "Testing", "Minimal test runner focused on parallelism and isolation", "avajs/ava"),

    # ORM additions
    ("kysely", "Kysely", "npm", "ORM", "Type-safe SQL query builder, growing fast among power users", "kysely-org/kysely"),
    ("mikro-orm", "MikroORM", "npm", "ORM", "TypeScript ORM with identity map and unit of work patterns", "mikro-orm/mikro-orm"),

    # Linting additions
    ("mypy", "mypy", "pypi", "Linting", "Python type checker — the one Ruff explicitly does not replace", "python/mypy"),
    ("pyright", "Pyright", "pypi", "Linting", "Microsoft's Python type checker, powers Pylance in VSCode", "microsoft/pyright"),
    ("isort", "isort", "pypi", "Linting", "Python import sorter, being absorbed into Ruff", "PyCQA/isort"),
    ("oxlint", "oxlint", "npm", "Linting", "Ultra-fast Rust-based JS linter, very early stage", "oxc-project/oxc"),

    # Package manager additions
    ("conda", "Conda", "pypi", "Package Manager", "Data science package manager, standard for ML/CUDA environments", "conda/conda"),
    ("bun", "bun", "npm", "Package Manager", "JavaScript runtime with integrated package manager and tooling", "oven-sh/bun"),

    # API framework additions
    ("litestar", "Litestar", "pypi", "API Framework", "FastAPI alternative with a cleaner API, growing among power users", "litestar-org/litestar"),
    ("elysia", "Elysia", "npm", "API Framework", "Bun-native API framework with end-to-end type safety", "elysiajs/elysia"),
    ("@trpc/server", "tRPC", "npm", "API Framework", "Type-safe API layer standard in TypeScript monorepos", "trpc/trpc"),
    ("@nestjs/core", "NestJS", "npm", "API Framework", "TypeScript enterprise framework with large installed base", "nestjs/nest"),
    ("h3", "h3", "npm", "API Framework", "Minimal HTTP framework powering modern server runtimes", "unjs/h3"),

    # UI component additions
    ("@radix-ui/react-primitive", "Radix UI", "npm", "UI Components", "Headless primitives that shadcn/ui is built on, growing independently", "radix-ui/primitives"),
    ("@headlessui/react", "Headless UI", "npm", "UI Components", "Unstyled accessible UI primitives for Tailwind and React", "tailwindlabs/headlessui"),

    # Bundler additions
    ("turbopack", "Turbopack", "npm", "Bundler", "Vercel's Rust-based webpack replacement, powers Next.js dev server", "vercel/turbo"),
    ("rspack", "Rspack", "npm", "Bundler", "Rust-powered bundler designed for webpack compatibility", "web-infra-dev/rspack"),

    # State management additions
    ("xstate", "XState", "npm", "State Management", "State machines and statecharts for complex UI logic", "statelyai/xstate"),
    ("recoil", "Recoil", "npm", "State Management", "Atom-based state management for React applications", "facebookexperimental/Recoil"),

    # AI/ML additions
    ("langgraph", "LangGraph", "pypi", "AI/ML", "Official LangChain path for new stateful agents, recommended over LangChain", "langchain-ai/langgraph"),
    ("crewai", "CrewAI", "pypi", "AI/ML", "Fastest-growing multi-agent framework with a clean role-based API", "crewAI-Inc/crewAI"),
    ("agno", "Agno", "pypi", "AI/ML", "High-performance multi-agent runtime, formerly Phidata, pre-commercial", "agno-agi/agno"),
    ("ollama", "Ollama", "pypi", "AI/ML", "Run LLMs locally — used broadly for private and on-device inference", "ollama/ollama"),
    ("openai-agents", "OpenAI Agents SDK", "pypi", "AI/ML", "First-party OpenAI multi-agent SDK released in 2025", "openai/openai-agents-python"),

    # AI Observability
    ("langfuse", "Langfuse", "pypi", "AI Observability", "LLM tracing, evals, and observability — fastest growing in category", "langfuse/langfuse"),
    ("logfire", "Logfire", "pypi", "AI Observability", "Pydantic's observability platform, tightly paired with PydanticAI", "pydantic/logfire"),
    ("sentry-sdk", "Sentry", "pypi", "AI Observability", "Error and performance monitoring frequently used in AI apps", "getsentry/sentry-python"),
    ("langsmith", "LangSmith", "pypi", "AI Observability", "LangChain's observability and eval layer, widely co-installed", "langchain-ai/langsmith-sdk"),
    ("mlflow", "MLflow", "pypi", "AI Observability", "Experiment tracking and model lifecycle tooling used in production ML", "mlflow/mlflow"),

    # Vector DB
    ("chromadb", "ChromaDB", "pypi", "Vector DB", "Accessible vector database often used in early-stage AI stacks", "chroma-core/chroma"),
    ("pgvector", "pgvector", "pypi", "Vector DB", "Postgres-native vector extension for semantic search", "pgvector/pgvector"),
    ("qdrant-client", "Qdrant", "pypi", "Vector DB", "High-performance vector search with growing enterprise adoption", "qdrant/qdrant"),
    ("pinecone-client", "Pinecone", "pypi", "Vector DB", "Managed vector database and early commercial leader", "pinecone-io/pinecone-python-client"),
    ("weaviate-client", "Weaviate", "pypi", "Vector DB", "Open-source vector DB with hybrid search", "weaviate/weaviate"),
    ("milvus", "Milvus", "pypi", "Vector DB", "High-scale open-source vector database for production retrieval", "milvus-io/milvus"),

    # Data Pipeline
    ("apache-airflow", "Apache Airflow", "pypi", "Data Pipeline", "De facto standard for data pipeline orchestration", "apache/airflow"),
    ("prefect", "Prefect", "pypi", "Data Pipeline", "Modern Airflow alternative, growing fast in data teams", "PrefectHQ/prefect"),
    ("dagster", "Dagster", "pypi", "Data Pipeline", "Asset-based orchestration used in mature data engineering teams", "dagster-io/dagster"),
    ("celery", "Celery", "pypi", "Data Pipeline", "Distributed task queue, stable mature infrastructure", "celery/celery"),
    ("temporal", "Temporal", "pypi", "Data Pipeline", "Workflow orchestration platform for reliability-critical systems", "temporalio/temporal"),
]

MCP_TOOLS = [
    ("@modelcontextprotocol/server-github", "MCP GitHub", "npm", "MCP Servers", "Official MCP server for GitHub — repos, issues, PRs", "modelcontextprotocol/servers"),
    ("@modelcontextprotocol/server-filesystem", "MCP Filesystem", "npm", "MCP Servers", "Official MCP server for local filesystem access", "modelcontextprotocol/servers"),
    ("@modelcontextprotocol/server-postgres", "MCP PostgreSQL", "npm", "MCP Servers", "Official MCP server for PostgreSQL database access", "modelcontextprotocol/servers"),
    ("@modelcontextprotocol/server-slack", "MCP Slack", "npm", "MCP Servers", "Official MCP server for Slack workspace access", "modelcontextprotocol/servers"),
    ("@modelcontextprotocol/server-google-maps", "MCP Google Maps", "npm", "MCP Servers", "Official MCP server for Google Maps and location data", "modelcontextprotocol/servers"),
    ("@modelcontextprotocol/server-brave-search", "MCP Brave Search", "npm", "MCP Servers", "Official MCP server for Brave web search", "modelcontextprotocol/servers"),
    ("@modelcontextprotocol/server-sqlite", "MCP SQLite", "npm", "MCP Servers", "Official MCP server for SQLite database", "modelcontextprotocol/servers"),
    ("@modelcontextprotocol/server-puppeteer", "MCP Puppeteer", "npm", "MCP Servers", "Official MCP server for browser automation via Puppeteer", "modelcontextprotocol/servers"),
    ("@upstash/context7-mcp", "Context7", "npm", "MCP Servers", "Up-to-date docs for any Cursor prompt via Upstash", "upstash/context7-mcp"),
    ("@exa-labs/exa-mcp-server", "Exa Search MCP", "npm", "MCP Servers", "AI-powered web search via Exa", "exa-labs/exa-mcp-server"),
    ("@supabase/mcp-server-supabase", "Supabase MCP", "npm", "MCP Servers", "MCP server for Supabase database and auth", "supabase/mcp-server-supabase"),
    ("@browserbasehq/mcp-server-browserbase", "Browserbase MCP", "npm", "MCP Servers", "Cloud browser automation via Browserbase", "browserbase/mcp-server-browserbase"),
    ("mcp-server-firecrawl", "Firecrawl MCP", "npm", "MCP Servers", "Web scraping and crawling for AI agents", "mendableai/firecrawl"),
    ("@microsoft/playwright-mcp", "Playwright MCP", "npm", "MCP Servers", "Browser automation via Playwright", "microsoft/playwright-mcp"),
    ("mcp-server-git", "MCP Git", "pypi", "MCP Servers", "MCP server for Git repository operations", "modelcontextprotocol/servers"),
    ("mcp", "MCP SDK Python", "pypi", "MCP Servers", "Official Python SDK for building MCP servers", "modelcontextprotocol/python-sdk"),
]

ALTERNATIVE_MAPPINGS = [
    ("sentry-sdk", "Datadog", "datadog", "Cloud monitoring and security platform", "datadog.com", "Observability", "partial"),
    ("sentry-sdk", "Sentry", "sentry", "Application monitoring and error tracking (commercial tier)", "sentry.io", "Observability", "full"),
    ("langfuse", "LangSmith", "langsmith", "LangChain's hosted LLM observability platform", "smith.langchain.com", "AI Observability", "full"),
    ("langfuse", "Datadog", "datadog", "Cloud monitoring and security platform", "datadog.com", "Observability", "partial"),
    ("logfire", "Datadog", "datadog", "Cloud monitoring and security platform", "datadog.com", "Observability", "partial"),
    ("logfire", "LangSmith", "langsmith", "LangChain's hosted LLM observability platform", "smith.langchain.com", "AI Observability", "partial"),
    ("apache-airflow", "Prefect Cloud", "prefect-cloud", "Managed workflow orchestration platform", "prefect.io", "Data Pipeline", "adjacent"),
    ("prefect", "Prefect Cloud", "prefect-cloud", "Managed workflow orchestration platform", "prefect.io", "Data Pipeline", "full"),
    ("dagster", "Prefect Cloud", "prefect-cloud", "Managed workflow orchestration platform", "prefect.io", "Data Pipeline", "adjacent"),
    ("dagster", "Databricks", "databricks", "Unified data analytics platform", "databricks.com", "Data Pipeline", "partial"),
    ("apache-airflow", "Databricks", "databricks", "Unified data analytics platform", "databricks.com", "Data Pipeline", "partial"),
    ("prisma", "PlanetScale", "planetscale", "Serverless MySQL platform", "planetscale.com", "Database", "adjacent"),
    ("drizzle-orm", "PlanetScale", "planetscale", "Serverless MySQL platform", "planetscale.com", "Database", "adjacent"),
    ("sqlalchemy", "Django ORM", "django-orm", "Django's built-in ORM (not standalone)", "djangoproject.com", "ORM", "adjacent"),
    ("fastapi", "AWS Lambda", "aws-lambda", "Serverless function execution", "aws.amazon.com", "API Framework", "partial"),
    ("hono", "Cloudflare Workers", "cloudflare-workers", "Edge serverless execution", "cloudflare.com", "API Framework", "partial"),
    ("pytest", "Pytest Enterprise", "pytest-enterprise", "Enterprise test management", "pytest.org", "Testing", "full"),
    ("playwright", "BrowserStack", "browserstack", "Cloud cross-browser testing platform", "browserstack.com", "Testing", "partial"),
    ("playwright", "Sauce Labs", "sauce-labs", "Cloud testing platform", "saucelabs.com", "Testing", "partial"),
    ("ruff", "SonarQube", "sonarqube", "Code quality and security platform", "sonarqube.org", "Linting", "partial"),
    ("eslint", "SonarQube", "sonarqube", "Code quality and security platform", "sonarqube.org", "Linting", "partial"),
    ("langchain", "OpenAI Assistants API", "openai-assistants", "OpenAI's hosted agent framework", "platform.openai.com", "AI/ML", "partial"),
    ("pydantic-ai", "OpenAI Assistants API", "openai-assistants", "OpenAI's hosted agent framework", "platform.openai.com", "AI/ML", "partial"),
    ("crewai", "AutoGen Studio", "autogen-studio", "Microsoft's multi-agent UI", "microsoft.com", "AI/ML", "partial"),
    ("llama-index", "Pinecone Assistant", "pinecone-assistant", "Pinecone's hosted RAG service", "pinecone.io", "AI/ML", "partial"),
    ("transformers", "OpenAI API", "openai-api", "OpenAI's proprietary model API", "api.openai.com", "AI/ML", "partial"),
    ("litellm", "OpenAI API", "openai-api", "OpenAI's proprietary model API", "api.openai.com", "AI/ML", "full"),
    ("chromadb", "Pinecone", "pinecone", "Managed vector database service", "pinecone.io", "Vector DB", "full"),
    ("qdrant-client", "Pinecone", "pinecone", "Managed vector database service", "pinecone.io", "Vector DB", "full"),
    ("weaviate-client", "Pinecone", "pinecone", "Managed vector database service", "pinecone.io", "Vector DB", "full"),
    ("pgvector", "Pinecone", "pinecone", "Managed vector database service", "pinecone.io", "Vector DB", "partial"),
    ("zustand", "Redux", "redux", "Predictable state container (commercial support)", "redux.js.org", "State Management", "full"),
    ("jotai", "Redux", "redux", "Predictable state container (commercial support)", "redux.js.org", "State Management", "full"),
    ("vite", "webpack", "webpack", "Module bundler", "webpack.js.org", "Bundler", "full"),
    ("esbuild", "webpack", "webpack", "Module bundler", "webpack.js.org", "Bundler", "full"),
    ("uv", "pip", "pip", "Python's default package installer", "pip.pypa.io", "Package Manager", "full"),
    ("poetry", "pip", "pip", "Python's default package installer", "pip.pypa.io", "Package Manager", "full"),
    ("pnpm", "npm", "npm", "Node.js default package manager", "npmjs.com", "Package Manager", "full"),
]

OFFICIAL_MCP_ORGS = {"modelcontextprotocol", "microsoft", "google", "anthropic"}

WEBSITE_DOMAINS = {
    "@modelcontextprotocol/server-github": "modelcontextprotocol.io",
    "@modelcontextprotocol/server-filesystem": "modelcontextprotocol.io",
    "@modelcontextprotocol/server-postgres": "modelcontextprotocol.io",
    "@modelcontextprotocol/server-slack": "modelcontextprotocol.io",
    "@modelcontextprotocol/server-google-maps": "modelcontextprotocol.io",
    "@modelcontextprotocol/server-brave-search": "modelcontextprotocol.io",
    "@modelcontextprotocol/server-sqlite": "modelcontextprotocol.io",
    "@modelcontextprotocol/server-puppeteer": "modelcontextprotocol.io",
    "@upstash/context7-mcp": "upstash.com",
    "@exa-labs/exa-mcp-server": "exa.ai",
    "@supabase/mcp-server-supabase": "supabase.com",
    "@browserbasehq/mcp-server-browserbase": "browserbase.com",
    "mcp-server-firecrawl": "firecrawl.dev",
    "@microsoft/playwright-mcp": "playwright.dev",
    "mcp-server-git": "modelcontextprotocol.io",
    "mcp": "modelcontextprotocol.io",
}

ALIASES = {
    # npm aliases
    "@tanstack/react-query": "react-query",
    "react-query": "react-query",
    "@prisma/client": "prisma",
    "drizzle-orm": "drizzle-orm",
    "@biomejs/biome": "biome",
    "shadcn": "shadcn-ui",
    "@shadcn/ui": "shadcn-ui",
    "redux": "@reduxjs/toolkit",
    "@trpc/client": "@trpc/server",

    # pypi aliases
    "scikit_learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "llama_index": "llama-index",
    "pydantic_ai": "pydantic-ai",
    "langchain_core": "langchain",
    "langchain_openai": "langchain",
    "langchain_anthropic": "langchain",
    "phidata": "agno",
    "langchain_community": "langchain",
    "openai_agents": "openai-agents",
}

STANDALONE_FIRST_TOOLS = {
    "ollama",
    "docker",
    "conda",
    "uv",
}

MIXED_TOOLS = {
    "sentry-sdk",
    "logfire",
    "langfuse",
    "langsmith",
}

PACKAGE_NAMES = {
    # canonical_name: (npm_package, pypi_package)
    "shadcn-ui": ("shadcn", None),
    "@mui/material": ("@mui/material", None),
    "@radix-ui/react-primitive": ("@radix-ui/react-primitive", None),
    "@reduxjs/toolkit": ("@reduxjs/toolkit", None),
    "@trpc/server": ("@trpc/server", None),
    "@nestjs/core": ("@nestjs/core", None),
    "@biomejs/biome": ("@biomejs/biome", None),
    "drizzle-orm": ("drizzle-orm", None),
    "pydantic-ai": (None, "pydantic-ai"),
    "llama-index": (None, "llama-index"),
    "langchain": (None, "langchain"),
    "langgraph": (None, "langgraph"),
    "crewai": (None, "crewai"),
    "sentry-sdk": (None, "sentry-sdk"),
    "apache-airflow": (None, "apache-airflow"),
    "qdrant-client": (None, "qdrant-client"),
    "pinecone-client": (None, "pinecone-client"),
    "weaviate-client": (None, "weaviate-client"),
    "chromadb": (None, "chromadb"),
    "pgvector": (None, "pgvector"),
    "pytest-asyncio": (None, "pytest-asyncio"),
}


def verify_package_exists(package_name: str, ecosystem: str) -> bool:
    """
    Quick registry existence check for package mappings.
    """
    if not package_name:
        return False
    try:
        if ecosystem == "npm":
            safe_package = quote(package_name, safe="@/")
            url = f"https://registry.npmjs.org/{safe_package}/latest"
            resp = requests.get(url, timeout=5)
            return resp.status_code == 200
        if ecosystem == "pypi":
            pkg = package_name.lower().replace("_", "-")
            url = f"https://pypi.org/pypi/{pkg}/json"
            resp = requests.get(url, timeout=5)
            return resp.status_code == 200
    except Exception:
        return False
    return False


def print_package_verification_report(conn) -> None:
    rows = conn.execute(
        """
        SELECT canonical_name, ecosystem, npm_package, pypi_package
        FROM tools
        ORDER BY canonical_name
        """
    ).fetchall()

    print("\nPackage Mapping Verification Report")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    missing = 0
    checked = 0

    for row in rows:
        ecosystem = row["ecosystem"]
        canonical = row["canonical_name"]
        if ecosystem == "npm":
            pkg = (row["npm_package"] or canonical or "").strip()
            if not pkg:
                continue
            ok = verify_package_exists(pkg, "npm")
            checked += 1
            if ok:
                print(f"✅  {canonical:<18} npm:{pkg:<28} → found")
            else:
                print(f"⚠️  {canonical:<18} npm:{pkg:<28} → NOT FOUND (check mapping)")
                missing += 1
        elif ecosystem == "pypi":
            pkg = (row["pypi_package"] or canonical or "").strip()
            if not pkg:
                continue
            ok = verify_package_exists(pkg, "pypi")
            checked += 1
            if ok:
                print(f"✅  {canonical:<18} pypi:{pkg:<27} → found")
            else:
                print(f"⚠️  {canonical:<18} pypi:{pkg:<27} → NOT FOUND (check mapping)")
                missing += 1

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"{missing}/{checked} tools have missing or incorrect package mappings.")
    if missing:
        print("Fix these in PACKAGE_NAMES dict in 01_seed_tools.py.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify npm/pypi package mappings against package registries",
    )
    args = parser.parse_args()

    init_db()
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO tools (
                canonical_name, display_name, ecosystem, category, description, github_repo
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            SEED_TOOLS + MCP_TOOLS,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO tool_aliases(alias, canonical_name) VALUES (?, ?)",
            list(ALIASES.items()),
        )

        # Default usage model and package names from canonical slugs.
        conn.execute(
            "UPDATE tools SET usage_model = 'dependency_first' WHERE usage_model IS NULL OR usage_model = ''"
        )
        conn.execute(
            "UPDATE tools SET npm_package = canonical_name WHERE ecosystem = 'npm' AND (npm_package IS NULL OR trim(npm_package) = '')"
        )
        conn.execute(
            "UPDATE tools SET pypi_package = canonical_name WHERE ecosystem = 'pypi' AND (pypi_package IS NULL OR trim(pypi_package) = '')"
        )

        for tool in STANDALONE_FIRST_TOOLS:
            conn.execute(
                "UPDATE tools SET usage_model = 'standalone_first' WHERE canonical_name = ?",
                (tool,),
            )
        for tool in MIXED_TOOLS:
            conn.execute(
                "UPDATE tools SET usage_model = 'mixed' WHERE canonical_name = ?",
                (tool,),
            )

        for canonical, (npm_pkg, pypi_pkg) in PACKAGE_NAMES.items():
            conn.execute(
                "UPDATE tools SET npm_package = ?, pypi_package = ? WHERE canonical_name = ?",
                (npm_pkg, pypi_pkg, canonical),
            )

        for canonical, domain in WEBSITE_DOMAINS.items():
            conn.execute(
                "UPDATE tools SET website_domain = ? WHERE canonical_name = ?",
                (domain, canonical),
            )

        for canonical, _, _, _, _, github_repo in MCP_TOOLS:
            org = github_repo.split("/")[0] if github_repo else ""
            is_official = 1 if org in OFFICIAL_MCP_ORGS else 0
            conn.execute(
                "UPDATE tools SET is_official = ? WHERE canonical_name = ?",
                (is_official, canonical),
            )

        seeded_alternatives = 0
        for mapping in ALTERNATIVE_MAPPINGS:
            canonical, prop_name, prop_slug, prop_desc, prop_website, prop_cat, alt_type = mapping
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO tool_alternatives (
                    canonical_name,
                    proprietary_name,
                    proprietary_slug,
                    proprietary_description,
                    proprietary_website,
                    proprietary_category,
                    alternative_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (canonical, prop_name, prop_slug, prop_desc, prop_website, prop_cat, alt_type),
            )
            seeded_alternatives += int(cur.rowcount or 0)
        conn.commit()

        category_rows = conn.execute(
            "SELECT category, COUNT(*) AS cnt FROM tools GROUP BY category ORDER BY category"
        ).fetchall()
        if args.verify:
            print_package_verification_report(conn)

    all_seed_tools = SEED_TOOLS + MCP_TOOLS
    category_counter = Counter(t[3] for t in all_seed_tools)
    print(f"Seeded {len(all_seed_tools)} tools across {len(category_counter)} categories")
    print("\nCategory | Count")
    print("---------|------")
    for row in category_rows:
        print(f"{row['category']} | {row['cnt']}")
    print("  -> Usage models updated")
    print(f"  -> Seeded {len(MCP_TOOLS)} MCP server tools")
    print(f"  -> Seeded {seeded_alternatives} alternative mappings")


if __name__ == "__main__":
    main()
