# Python AI Project Structure

Source: https://www.decodingai.com/p/how-to-design-python-ai-projects  
Pattern: "Pragmatic clean architecture" — virtual conceptual layers, not rigid folders.

---

## Four Conceptual Layers

Layers are **mental models**, not folder names. Never create directories called `domain/`, `application/`, `infrastructure/`.

| Layer | Purpose | Contains |
|---|---|---|
| **Domain** (the *what*) | Business entities and atomic AI units | Pydantic models, Node classes (prompt + logic), independent/reusable units |
| **Application** (the *how*) | Orchestrates domain components | Workflows, business logic sequencing (e.g. LangGraph graphs) |
| **Infrastructure** (the *external*) | Concrete external implementations | LLM clients, DB connections, storage (disk, S3), vector index clients |
| **Serving** (the *interface*) | Exposes functionality | CLI, REST API, MCP server |

**Dependency rule**: outer layers know inner layers; inner layers never import from outer. Core business logic must be infrastructure-agnostic.

---

## Recommended Folder Structure

```
my-project/
├── pyproject.toml
├── Makefile
├── configs/          # Configuration files (model params, env-specific settings)
├── inputs/           # Sample or fixture input data
├── scripts/          # One-off scripts, data prep, admin tasks
├── notebooks/        # Exploratory notebooks (not production code)
├── tests/
└── src/
    └── <package>/
        ├── entities/       # Pydantic data models
        ├── nodes/          # Atomic AI units (prompt + logic per task)
        ├── workflows/      # Orchestration (assembles nodes into use cases)
        ├── models/         # LLM/embedding model abstractions
        ├── memory/         # Conversation memory, state management
        ├── mcp/            # MCP server definitions
        ├── evals/          # Evaluation logic and datasets
        ├── observability/  # Logging, tracing, metrics
        ├── utils/          # Shared helpers
        └── base.py         # Abstract base classes / shared interfaces
```

Organize by **functionality/feature**, not by file type. All logic for a specific task lives together.

---

## Key Design Rules

**Decouple only what is worth decoupling.** Don't build abstractions for hypothetical future scenarios. Simplicity over architectural purity.

**Use abstract interfaces (protocols/ABCs) for swappable components.** A `BaseLLM`, `BaseEncoder`, `BaseIndex` pattern lets you swap implementations without touching application code.

**Actionability over taxonomy.** A node/module should be copy-pasteable into another project and work. Cohesion > DRY in AI projects.

---

## Mistakes to Avoid

| Mistake | Problem | Fix |
|---|---|---|
| Folders named `domain/`, `application/`, `infrastructure/` | Forces artificial splits, causes circular imports | Flat hierarchy scoped by functionality |
| Folders named `prompts/`, `nodes/`, `chains/` | Scatters logic for one feature across multiple dirs | Keep all logic for one task in one place |
| Over-engineering | Abstractions for hypothetical scenarios add complexity with no payoff | Build for today's requirements |

---

## Data Flow

```
Request → Serving layer
        → instantiates Infrastructure (LLM client, DB, index)
        → injects into Application (workflow/orchestrator)
        → executes Domain nodes
        → returns result back up the stack
```

---

## Relevance to This Project

Apply this to the `embeddings` package structure:

```
src/
└── embeddings/
    ├── entities/       # Pydantic models: Document, Chunk, SearchResult, EmbeddingVector
    ├── nodes/          # Atomic units: ingest_document, encode_chunk, search_index
    ├── workflows/      # Orchestrated flows: ingest_pipeline, agentic_search_flow
    ├── models/         # Encoder abstractions: BaseEncoder, TextEncoder, ImageEncoder, AudioEncoder
    ├── index/          # Index abstractions: BaseIndex, FAISSIndex, QdrantIndex
    ├── agents/         # Claude Agent SDK agent definitions and tool bindings
    ├── serving/        # CLI, HTTP API, MCP server
    ├── evals/          # Retrieval quality evaluations
    ├── observability/  # Logging, tracing
    ├── utils/
    └── base.py         # Shared ABCs / protocols
```

The layered architecture from the project vision maps cleanly:
- Ingestion + Embedding → `nodes/` + `models/`
- Index → `index/`  
- Search → `workflows/` or `nodes/`
- Agent → `agents/`
- API/CLI → `serving/`
