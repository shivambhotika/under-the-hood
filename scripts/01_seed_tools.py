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
    # pypi aliases
    "scikit_learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "llama_index": "llama-index",
    "pydantic_ai": "pydantic-ai",
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
