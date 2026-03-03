from __future__ import annotations

from collections import Counter

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
    ("anthropic", "Anthropic SDK", "pypi", "AI/ML", "Official Python client for the Anthropic API", "anthropic/anthropic-sdk-python"),
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


def main() -> None:
    init_db()
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO tools (
                canonical_name, display_name, ecosystem, category, description, github_repo
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            SEED_TOOLS,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO tool_aliases(alias, canonical_name) VALUES (?, ?)",
            list(ALIASES.items()),
        )
        conn.commit()

        category_rows = conn.execute(
            "SELECT category, COUNT(*) AS cnt FROM tools GROUP BY category ORDER BY category"
        ).fetchall()

    category_counter = Counter(t[3] for t in SEED_TOOLS)
    print(f"Seeded {len(SEED_TOOLS)} tools across {len(category_counter)} categories")
    print("\nCategory | Count")
    print("---------|------")
    for row in category_rows:
        print(f"{row['category']} | {row['cnt']}")


if __name__ == "__main__":
    main()
