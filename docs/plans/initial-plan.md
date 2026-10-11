# Role and Mission

You are a senior full-stack software engineer, AI systems architect, and experienced coding-agent collaborator.

Your task is to design and subsequently implement **AI Research Assistant**, a full-stack web application for **CS 59300 — AI-Assisted Software Engineering**, according to `@hw1.md`.

The application should demonstrate modern software-engineering practices, asynchronous Python development, LLM integration, document intelligence, and effective AI-assisted software development.

Our objective is to build a polished, reliable, maintainable application with a reasonably sophisticated architecture, while keeping development and deployment reproducible on a local machine using Docker Compose.

**Your immediate task is to produce a detailed, technically validated implementation plan—not to implement the entire application yet.** Once the plan has been reviewed, implementation will proceed incrementally through well-defined phases.

## 1. Understand the Assignment and Establish Priorities

Read `@hw1.md` carefully and treat it as the authoritative source of functional requirements, grading criteria, submission deliverables, and deadlines.

The application must support at least:

1. Searching research papers using an external academic search API.
2. Saving papers to a persistent personal research library.
3. Uploading PDFs and extracting paper metadata.
4. Generating LLM summaries grounded in the actual paper content.
5. Asking natural-language questions about individual papers.

The graphical interface, backend, persistent storage, external API integration, and LLM integration are mandatory.

The assignment also requires a GitHub repository, a demonstration video, and a reflection report documenting the coding-agent development experience.

Build a requirements traceability matrix connecting each homework requirement to its implementation components, tests, and demonstration steps.

**Prioritization rule:** All mandatory homework workflows must function end-to-end before optional engineering enhancements.

Classify features into:

- **P0 — Mandatory:** Everything needed for a complete, demonstrable homework submission, including the chosen containerized development foundation.
- **P1 — Important:** Architectural and user-experience improvements that are part of our intended system.
- **P2 — Optional:** Advanced capabilities that may depend on hardware, external services, or remaining development time.

## 2. Required Technology Stack

Use the following technologies unless investigation reveals a compelling technical incompatibility. Document and justify any proposed deviation.

### Frontend

- React with Vite
- TypeScript, with strict type checking
- Tailwind CSS v4
- shadcn/ui
- TanStack Query for server state, caching, and asynchronous requests
- Zustand only if shared client-side state becomes sufficiently complex
- React Router or TanStack Router, selected with justification
- React Hook Form and Zod where appropriate

Prefer a clean, maintainable SPA architecture.

### Backend

- Python, using a supported modern version
- FastAPI
- Pydantic v2
- Pydantic Settings for configuration
- SQLAlchemy 2.x with asynchronous database sessions
- Alembic for database migrations
- PostgreSQL
- psycopg 3 with async support
- httpx for asynchronous external HTTP requests
- Redis as the background-task message broker
- Dramatiq as the background-task framework

Keep business logic in Python. Use a layered backend design separating API routes, schemas, domain models, services, repositories, external integrations, and background jobs.

Avoid unnecessary abstractions and premature microservice decomposition.

### Storage and Document Processing

- PostgreSQL for relational data
- MinIO for S3-compatible object storage
- PyMuPDF for PDF text and metadata extraction
- PostgreSQL native full-text search for initial retrieval
- pgvector as the preferred optional extension for semantic retrieval

Store PDF files in MinIO and their metadata, processing state, and object references in PostgreSQL.

Do not store entire PDF binaries directly inside PostgreSQL.

### External Academic Search

Implement both:

- Semantic Scholar API
- OpenAlex API

The user must be able to select which provider to search.

Use separate provider adapters behind a consistent internal search interface. Normalize provider responses into shared Pydantic schemas.

Handle differences in identifiers, metadata completeness, available abstracts, and downloadable PDF URLs.

### Development Tooling

- uv for Python dependency management
- Ruff for Python linting and formatting
- pytest, pytest-asyncio, and httpx for backend testing
- Vitest and React Testing Library for frontend testing
- Playwright for browser end-to-end testing
- ESLint and TypeScript type checking
- Docker and Docker Compose
- Git and GitHub

Use lockfiles and reproducible dependency versions.

## 3. Docker-First Development Architecture

Everything should run locally through Docker Compose.

The default development environment should include:

1. `frontend` — React/Vite development server
2. `api` — FastAPI application
3. `worker` — Dramatiq background worker
4. `postgres` — PostgreSQL database
5. `redis` — Redis broker
6. `minio` — S3-compatible object storage

Introduce small initialization or migration services where necessary, rather than assuming dependencies are ready merely because containers have started.

### Development Requirements

- Support frontend hot module replacement.
- Support FastAPI automatic reload.
- Provide a practical worker-code reload or automatic worker-restart development workflow.
- Bind-mount source code where appropriate so ordinary code changes do not require rebuilding Docker images.
- Rebuild images when dependencies or Dockerfiles change.
- Use named volumes for PostgreSQL, MinIO, and any other persistent state.
- Provide health checks and appropriate service startup dependencies.
- Automatically initialize required MinIO buckets.
- Provide database initialization through Alembic migrations.
- Keep development ports and service URLs configurable.
- Configure local frontend/backend networking and CORS correctly.
- Support clean startup and shutdown.
- Avoid exposing internal databases and storage services unnecessarily.
- Provide `.env.example` with documented configuration values.
- Ensure no secrets or persistent generated data are committed to Git.

The system should be runnable using a documented command such as:

`docker compose up --build`

After the initial build, routine source-code edits should not require rebuilding the images.

Local LLM inference must be optional and should not prevent the default application services from starting.

Document how to inspect service logs, apply migrations, run tests, and reset development data safely.

## 4. Asynchronous Programming and Background Processing

Follow asynchronous programming principles where they provide meaningful benefits.

Use asynchronous FastAPI endpoints and SQLAlchemy `AsyncSession` for I/O-heavy database operations.

Use Redis + Dramatiq for long-running or resource-intensive tasks, including:

- PDF ingestion and validation
- PDF text extraction
- Paper metadata extraction
- Automatic retrieval of accessible full-text PDFs
- Document chunking and indexing
- Embedding generation, if enabled
- Paper summarization
- Other long-running LLM operations

**Distinguish asynchronous request handling from background job execution.**

Do not force CPU-heavy PDF extraction into the FastAPI event loop. Run it in worker processes.

For interactive chat, prefer direct streaming from FastAPI using Server-Sent Events (SSE), unless a more appropriate architecture is justified.

Design the job system with:

- Persistent job records in PostgreSQL
- Explicit queued, processing, completed, and failed states
- Progress/status endpoints
- User-visible job status and error reporting
- Controlled retries and exponential backoff
- Idempotent task behavior where possible
- Transaction-safe updates
- Recovery behavior for interrupted jobs
- Appropriate job timeouts
- Duplicate-job prevention where appropriate

Investigate the compatibility of Dramatiq actors with asynchronous SQLAlchemy sessions and event-loop management. Use Dramatiq's AsyncIO middleware when appropriate, and never share database sessions across tasks or incompatible event loops.

For each background task, document its inputs, outputs, failure conditions, retry strategy, and effect on persistent state.

## 5. Strong Typing, Data Modeling, and API Contracts

Use Pydantic extensively for validation, serialization, configuration, and structured interfaces.

Use SQLAlchemy models for database persistence and Pydantic schemas for external API contracts and application DTOs.

Do not conflate database models with API response models.

At minimum, evaluate the following domain entities:

- Paper
- PaperAuthor or equivalent normalized author representation
- PaperSource / external identifiers
- Document / stored PDF
- DocumentChunk
- ChatSession
- ChatMessage
- PaperSummary
- BackgroundJob
- ModelConfiguration or model registry metadata

Model relationships clearly, particularly the association between papers, chats, messages, files, summaries, and processing jobs.

### Data Integrity

- Support paper identification by DOI and provider-specific identifiers.
- Avoid duplicate saved papers across search providers.
- Preserve metadata provenance.
- Allow users to correct incorrectly extracted metadata.
- Preserve the original uploaded PDF.
- Store generated summaries and chat history persistently.
- Track the model and effective generation settings used for LLM responses.
- Use Alembic migrations rather than ad hoc production schema creation.

Define consistent API response schemas, structured error responses, validation rules, and HTTP status codes.

Use OpenAPI generated by FastAPI as the API contract. Consider generating TypeScript API types or clients rather than manually duplicating interfaces.

## 6. Paper Search and Library Workflow

The research search interface must provide a clear provider selector:

- Semantic Scholar
- OpenAlex

Both providers should return a normalized paper-search result containing, where available:

- Title
- Authors
- Publication year
- Abstract
- DOI
- External paper URL
- Open-access PDF URL
- Source provider and external identifier

Implement pagination or incremental loading where supported.

Provide meaningful handling for:

- Missing abstracts or metadata
- API timeouts
- Rate limits
- Invalid or missing credentials
- Network outages
- Empty results
- Duplicate papers
- Papers without accessible full text

Search-provider integrations should use explicit timeouts, bounded retries, and appropriate backoff.

Users must be able to save papers, browse the persistent library, select a paper, and inspect its details.

For papers saved from a search result, distinguish between having **metadata only** and having the **actual full text**.

When an accessible open-access PDF is available, support retrieval and processing through the ingestion pipeline.

When the full text is unavailable, prompt the user to upload the PDF rather than presenting metadata-only analysis as full-paper analysis.

## 7. PDF Processing and Document Intelligence

Use PyMuPDF for PDF processing.

The pipeline should:

1. Validate the uploaded file.
2. Store the original PDF in MinIO.
3. Create the appropriate database and background-job records.
4. Extract document text, retaining page boundaries.
5. Extract title, authors, publication year, and abstract.
6. Use an LLM with structured Pydantic output where deterministic metadata extraction is insufficient.
7. Persist the extracted metadata and full text or corresponding text chunks.
8. Prepare the paper for summarization and Q&A.

Do not fabricate metadata when extraction is uncertain.

Support manual correction of extracted fields.

Keep page references and source provenance to enable grounded answers with citations.

Handle malformed, encrypted, oversized, scanned, and image-only PDFs gracefully. OCR can be proposed as an optional extension rather than a mandatory dependency.

Enforce reasonable upload size and page-count limits.

Treat PDF contents as untrusted data, never as executable system instructions.

### PDF Skill

The following third-party skill has been suggested:

https://lobehub.com/skills/openclaw-skills-pymupdf-pdf-parser-clawdbot-skill/skill.md

Before installing anything from this source:

- Inspect its contents, provenance, and any referenced scripts or dependencies.
- Evaluate prompt-injection, shell execution, network access, and credential-exfiltration risks.
- Compare its utility with official PyMuPDF documentation.
- Do not blindly execute remote installation commands.
- Report security concerns and request approval if the skill is questionable.

If it is suitable and approved, install it into `.agents/skills` according to the supported skill format.

The application must remain functional without that optional agent skill.

## 8. LLM Integration and Model Management

Implement a provider-agnostic LLM service layer in Python.

The frontend should interact only with our FastAPI backend, never directly with third-party LLM APIs using exposed credentials.

### OpenAI Models

Support the following model IDs, subject to account availability:

- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `gpt-5.6-luna`

Use the official OpenAI Python SDK and the appropriate supported API.

### Locally Hosted Models

Investigate support for:

- `IFM/K2-Horizon-7B`
- `Qwen/Qwen3.8-27B`

For Qwen, investigate Q4_K_M quantization as requested.

The preferred local serving engine is vLLM, exposing an OpenAI-compatible API.

However, do not assume that every model and quantization format works reliably with vLLM.

Before planning implementation, verify:

- Exact model repositories and releases
- Licenses and applicable usage conditions
- GPU/CUDA compatibility
- Approximate VRAM and system-memory requirements
- Supported context lengths under realistic hardware limits
- Quantization compatibility
- Streaming support
- Reasoning-control capabilities
- API compatibility

If vLLM cannot reliably serve the requested GGUF Q4_K_M artifact, evaluate a compatible quantization or llama.cpp as an explicitly documented alternative.

Do not automatically download multi-gigabyte model weights during the default Docker setup.

Use an optional Docker Compose profile such as `local-llm`, and provide clear hardware prerequisites.

### Model Selection and Reasoning

Users should be able to:

- Select an available model.
- Configure reasoning effort when the selected model supports it.
- Start and continue multi-turn conversations.
- Preserve conversation history.
- Associate chats with a specific research paper.
- View previous conversations for each paper.
- See which model generated each response.

Maintain model capability metadata rather than assuming every provider supports identical settings.

Unsupported reasoning parameters should be disabled or handled explicitly.

Handle unavailable models, missing credentials, provider errors, and rate limits gracefully.

The application must remain usable with a configured hosted model even when local model serving is unavailable.

## 9. Context Management, RAG, and Grounded Q&A

A paper research assistant must provide document-grounded answers rather than generic chatbot responses.

Design a retrieval pipeline that supports:

- Full-text extraction
- Page-aware text chunking
- Chunk metadata and source references
- Context retrieval for a question
- Token-budget-aware context construction
- Conversation-history management
- Grounded answer generation
- Source/page citations
- Clear handling of insufficient evidence

Start with PostgreSQL full-text retrieval if necessary.

Evaluate pgvector and embeddings as a later enhancement for semantic or hybrid retrieval.

Choose a simple, understandable retrieval design rather than introducing an extensive orchestration framework without a demonstrated need.

For multi-turn chat, explicitly define:

- The paper associated with the conversation
- Stored user and assistant messages
- Conversation-window or summarization strategy
- Retrieval context for each query
- Model-specific context limits
- Token budgets and truncation behavior
- How prior messages affect follow-up questions

Ensure paper summaries use actual extracted paper content.

If the paper has not been processed, the application should show that processing is required rather than inventing an answer.

Show citations or page references whenever the retrieved content provides sufficient provenance.

Keep generated text distinguishable from source text.

Handle prompt-injection attempts embedded in uploaded documents by treating retrieved passages as lower-trust source material.

## 10. Configuration, Security, and Reliability

Use Pydantic Settings for centralized configuration management.

Support environment variables and local `.env` files. An optional ignored local configuration file can be supported if justified.

Environment variables should take precedence according to a documented configuration policy.

Allow optional credentials for:

- OpenAI
- Semantic Scholar
- OpenAlex
- MinIO and other internal services

Never expose API keys to the browser, commit them to Git, or print them in logs.

For this local-first homework, assume a single-user application unless requirements indicate otherwise. Do not introduce a full authentication or multi-tenant system unnecessarily.

Include reasonable safeguards:

- PDF content-type and file signature validation
- Upload-size restrictions
- Safe object keys and filenames
- Protection against unsafe arbitrary-URL PDF downloads
- External API timeouts and backoff
- Clear errors for missing credentials
- Safe exception handling
- Structured application logging
- Basic LLM token and cost controls
- Cancellation or interruption handling where practical
- Protection against malformed provider responses

The system should degrade gracefully when individual external providers are unavailable.

## 11. Frontend Experience and Design

Use the Impeccable design plugin if it is available and appropriate. Otherwise, follow professional UI/UX principles using Tailwind CSS and shadcn/ui.

Build a polished but practical academic research interface.

The design should emphasize reading, searching, organizing papers, and conducting paper-grounded conversations—not a generic marketing landing page.

Plan the following views:

- Research search
- Search results
- Saved paper library
- Paper details
- PDF upload and processing
- Paper summaries
- Paper-associated chat
- Model and reasoning settings
- Background-job status and errors

Important UX capabilities:

- Responsive layout
- Clear navigation
- Accessible controls and keyboard interactions
- Consistent typography and spacing
- Loading, empty, success, and error states
- Visible paper-processing status
- Streaming chat responses
- Persistent chat history
- Paper-source and page citations
- Clear indication when no full-text content is available
- Usable mobile layouts

Create a small, consistent design system rather than independently styling every screen.

## 12. TDD, BDD, and Quality Assurance

**Test-Driven Development and Behavior-Driven Development are central requirements of our engineering workflow.**

For every feature, follow a red-green-refactor cycle wherever practical:

1. Define expected behavior and acceptance criteria.
2. Write a failing test or executable behavioral specification.
3. Implement the smallest solution that satisfies it.
4. Run the relevant tests.
5. Refactor without changing behavior.
6. Run regression tests.
7. Update the issue and record the outcome.

Write BDD-style Given/When/Then acceptance scenarios for user-facing features.

Example:

**Scenario: Ask a question about an uploaded research paper**

- Given a paper whose PDF has been processed and indexed,
- When the user asks a question about its methodology,
- Then the system retrieves relevant content from that paper,
- And sends the context to the selected LLM,
- And displays the answer in the paper's chat history,
- And includes supporting page references when available,
- And persists the messages after a page refresh.

### Backend Testing

Use pytest with appropriate asynchronous fixtures and testing support.

Cover:

- Domain models and Pydantic validation
- Search provider adapters
- Metadata normalization and deduplication
- PDF extraction
- Database repositories and migrations
- API endpoints
- Background-job transitions
- Task retries and idempotency
- LLM provider adapters
- Context management and retrieval
- Error handling

Mock external services for deterministic unit tests.

Use real PostgreSQL, Redis, and MinIO services in selected integration tests where their actual behavior matters.

### Frontend Testing

Use Vitest and React Testing Library for components, hooks, and integration behavior.

Test:

- Search forms and provider selection
- Paper cards and library interactions
- Upload status and errors
- Model selection
- Chat message rendering
- Loading and streaming states
- API failure handling

### End-to-End Testing

Use Playwright to cover the required homework workflows.

At minimum, plan one reliable end-to-end scenario for each of the five major assignment features.

Design deterministic test fixtures and mock LLM responses where appropriate so tests do not depend on paid API access.

Add real-service smoke tests separately.

Don't claim tests pass unless they were actually executed successfully.

## 13. Issue Tracking and Coding-Agent Development Records

Treat `@issue_tracker` as our Jira-like project tracker.

First, inspect how this tracker is exposed and what operations it supports. If it is unavailable, propose a simple repository-local issue tracker with stable issue identifiers.

Create trackable issues for:

- Features
- Bugs
- Improvements
- Infrastructure tasks
- Testing tasks
- Documentation tasks

Each issue should contain:

- Issue ID and title
- Description and motivation
- Priority
- Dependencies
- Acceptance criteria
- Relevant test cases
- Current status
- Related code files
- Related commits or pull requests, where available

Use issue identifiers in commits where practical.

### Coding-Agent Reflection Evidence

The homework explicitly evaluates our experience working with a coding agent.

Maintain a development journal, such as `docs/agent-development-log.md`, covering:

- Significant prompts given to Codex
- Architectural decisions and their rationale
- Incorrect or incomplete agent-generated implementations
- Build failures, test failures, and integration difficulties
- How the problem was diagnosed
- Follow-up prompts and corrective actions
- Resulting code or behavioral changes
- Evidence that the correction worked
- References to relevant issues and commits
- Suggested screenshots to capture for the final reflection

Do not invent failures or fabricate coding-agent interactions.

When a meaningful failure occurs, preserve enough visible context to reconstruct it later. Include visible intermediate output where available, but do not claim access to hidden internal reasoning.

Do not capture or expose secrets in logs or screenshots.

This journal should support the student's own authentic reflection rather than automatically fabricating a polished narrative.

## 14. AGENTS.md and Project Documentation

Create and maintain an `AGENTS.md` file as the repository's persistent agent-facing development guide.

It should document:

- Project purpose and requirements
- Technology stack
- Repository organization
- Architecture boundaries
- Development commands
- Testing commands
- Coding conventions
- Async programming conventions
- Database migration conventions
- Issue tracking workflow
- Definition of Done
- Known limitations and development constraints

Keep `AGENTS.md` concise and update it when important technical decisions change.

Use additional files under `docs/` for detailed architectural decisions, implementation plans, API references, and development observations.

Treat these files as documented shared context—not as a substitute for verifying the current repository state.

## 15. External Tools and Documentation

Use Context7 MCP when available to retrieve up-to-date documentation for libraries, frameworks, and integration patterns.

Prefer official documentation and verified APIs over assumptions or obsolete examples.

In particular, verify:

- FastAPI async practices
- SQLAlchemy async session management
- Dramatiq worker lifecycle and middleware
- Redis configuration
- PostgreSQL and Alembic integration
- MinIO S3 API compatibility
- PyMuPDF APIs
- Semantic Scholar and OpenAlex interfaces
- OpenAI model capabilities
- vLLM model and quantization support
- Tailwind CSS v4 and shadcn/ui configuration
- Vitest and Playwright setup

Record material technical findings and compatibility risks in the implementation plan.

If a requested plugin, MCP server, or skill is unavailable, explain the limitation and propose an appropriate fallback rather than pretending it was used.

## 16. Scope and Engineering Principles

Follow these principles throughout the project:

- Prefer a modular monolith over premature microservices.
- Keep Python responsible for backend and AI logic.
- Favor typed interfaces and explicit contracts.
- Keep background jobs idempotent where possible.
- Avoid unnecessary infrastructure and framework abstractions.
- Do not add authentication, payment processing, or enterprise multi-tenancy unless justified.
- Do not make GPU inference a prerequisite for the core application.
- Optimize for maintainability, reproducibility, and a functioning homework demo.
- Make dependencies between features explicit.
- Prioritize working end-to-end vertical slices over many partially implemented components.
- Avoid silently changing agreed architectural decisions.
- Document significant tradeoffs.
- Never claim an integration is working without verification.

Use sensible defaults when requirements are underspecified, and clearly distinguish requirements from your own implementation assumptions.

## 17. Multi-Agent Orchestration and Task Delegation

Act as the **lead engineering agent and project orchestrator**.

Whenever the Codex environment supports spawning or delegating to specialized subagents, actively use that capability to parallelize independent work, investigate technical problems, and review implementations.

Do not attempt to perform every task sequentially when meaningful parallelism is possible.

### Specialized Agent Responsibilities

Consider deploying agents with the following responsibilities:

1. **Architecture Agent:** Research architectural decisions, service boundaries, database modeling, API contracts, and technical tradeoffs.

2. **Backend Agent:** Implement Python/FastAPI services, Pydantic schemas, asynchronous SQLAlchemy repositories, Alembic migrations, and business logic.

3. **Frontend Agent:** Implement React/TypeScript interfaces, Tailwind CSS v4, shadcn/ui components, accessibility, and frontend state management. Use the Impeccable design plugin when available.

4. **AI/LLM Agent:** Investigate and implement LLM provider integrations, model capabilities, conversational context management, RAG, paper summarization, and document-grounded Q&A.

5. **Infrastructure Agent:** Develop and validate Docker Compose, PostgreSQL, Redis, Dramatiq, MinIO, development hot reloading, health checks, and persistent volumes.

6. **QA and Security Agent:** Develop and review tests, investigate failures, check security concerns, validate acceptance criteria, and identify regressions.

These are responsibilities, not a requirement to spawn six agents for every task. Choose the minimum effective number of agents based on task complexity, independence, and available resources.

### Delegation Principles

- The lead agent owns the overall architecture, implementation roadmap, integration, and final verification.
- Delegate independent research and implementation tasks to specialized agents when doing so provides clear benefits.
- Prefer parallel execution for tasks without shared dependencies.
- Define explicit interfaces and contracts before delegating interconnected components.
- Assign clear file or module ownership to avoid conflicting concurrent edits.
- Do not allow multiple agents to modify the same files simultaneously without coordination.
- Each delegated task must have a clear objective, scope, expected deliverables, and acceptance criteria.
- Require agents to report findings, modifications, test results, limitations, and unresolved issues.
- The lead agent must review and integrate delegated work rather than accepting it without verification.
- Track delegated tasks and discovered problems in `@issue_tracker`.
- Preserve meaningful agent interactions and corrections for the homework reflection report.

### Planning Phase

During the initial planning phase, delegate independent research tasks where appropriate, such as:

- Backend/database architecture
- Frontend design and component strategy
- LLM inference and model compatibility
- Docker infrastructure and deployment feasibility
- Testing strategy and requirement analysis

Consolidate findings into a single coherent implementation plan.

Identify conflicting recommendations and resolve them explicitly before implementation.

Do not start substantial application implementation during the planning phase.

### Implementation Phase

After approval of the implementation plan:

1. Break the current phase into well-defined issues.
2. Identify task dependencies and opportunities for parallel execution.
3. Assign independent tasks to suitable specialized agents.
4. Coordinate shared interfaces, schemas, and configuration.
5. Integrate completed work incrementally.
6. Execute relevant tests and verify acceptance criteria.
7. Record failures, corrections, and decisions in the issue tracker and development journal.
8. Proceed only after the current milestone satisfies its Definition of Done.

### Tool Availability and Fallbacks

Use native Codex subagent delegation capabilities when available.

If the current environment does not support subagents, continue using the main agent sequentially and clearly document the limitation.

Do not simulate successful agent deployment, fabricate delegated work, or claim that a tool or agent was used when it was not.

**The objective is to use multi-agent software engineering effectively while preserving coherent architecture, traceability, code quality, and accountability.**

## 18. Required Implementation Plan

Produce a detailed plan in `docs/implementation-plan.md`.

The plan must include:

### A. Requirements Analysis

- Mandatory homework requirements
- Proposed additional capabilities
- Requirements traceability matrix
- P0/P1/P2 priorities
- Functional acceptance criteria
- Assumptions and unresolved questions

### B. Architecture

- High-level system architecture
- Docker Compose service diagram
- Service responsibilities
- Data flows and API boundaries
- Background-task architecture
- PDF ingestion and retrieval pipelines
- Chat streaming architecture
- LLM provider abstraction
- Infrastructure and resource dependencies

Use Mermaid diagrams where useful.

### C. Data Design

- Proposed database schema
- Entity relationships
- Important constraints and indexes
- File/object storage strategy
- Job state transitions
- Migration strategy
- Conversation and message persistence

### D. API Design

Propose the main endpoints, request and response schemas, and error cases for:

- Research search
- Paper library management
- PDF upload and ingestion
- Background-job status
- Summarization
- Paper chat and streaming
- Conversation history
- Available models and configuration

### E. Testing Strategy

- TDD workflow
- BDD scenarios
- Unit tests
- Integration tests
- E2E tests
- Mocking strategy
- CI checks
- Test fixtures and demo datasets

### F. Phased Development Roadmap

Break implementation into small, independently verifiable phases, for example:

**Phase 0 — Foundation**

Repository organization, Docker Compose, development containers, PostgreSQL, Redis, MinIO, backend/frontend scaffolding, migrations, configuration, AGENTS.md, and testing foundations.

**Phase 1 — Paper Search and Library**

Semantic Scholar, OpenAlex, normalized search results, provider selection, persistence, deduplication, and library interface.

**Phase 2 — PDF Ingestion**

MinIO storage, upload validation, background processing, PyMuPDF extraction, metadata extraction, and processing status UI.

**Phase 3 — LLM Summarization and Paper Chat**

Hosted-model integration, summaries, persistent multi-turn chats, streaming, model selection, and document-grounded Q&A.

**Phase 4 — Retrieval and Advanced Capabilities**

Improved chunk retrieval, page citations, optional embeddings/pgvector, local-model serving, and advanced model settings.

**Phase 5 — Verification and Submission**

Integration and E2E tests, debugging, UX polish, README, demonstration preparation, reflection evidence, and final verification.

Adjust the phases if a more effective dependency order is identified.

For each phase include:

- Goals
- Scope and deliverables
- Dependencies
- Prioritized tasks
- Relevant issue identifiers
- Acceptance criteria
- Required tests
- Risks
- Estimated effort
- Concrete milestone

Build the schedule around the actual homework deadline. Highlight features that may be deferred if time becomes constrained.

### G. Definition of Done

Define what must be true before a phase or feature is considered complete.

At minimum:

- Acceptance criteria are satisfied.
- Relevant automated tests pass.
- No known critical regression remains.
- Required API and data changes are documented.
- Docker development workflow still works.
- Persistent data survives intended container restarts.
- Issue tracker is updated.
- Coding-agent learning or debugging evidence is recorded when relevant.

## 19. How to Begin

For this first interaction:

1. Inspect the repository and available reference files.
2. Read `@hw1.md` and distinguish authoritative requirements from sample material.
3. Check the available tools, plugins, MCP servers, and issue tracker.
4. Identify environment and hardware constraints relevant to local LLM serving.
5. Validate major technology assumptions using current documentation.
6. Identify requirements conflicts, technical uncertainties, and risks.
7. Prepare the architecture and detailed implementation plan.
8. Create or update planning documentation as appropriate.
9. Present a concise architectural summary, prioritized roadmap, and the first implementation milestone.

During planning, identify opportunities to deploy specialized agents. During implementation, actively delegate independent tasks and coordinate their integration. Treat effective multi-agent collaboration as an explicit part of the AI-assisted software-engineering experiment, and document both its successes and failures for the reflection report.

**Do not start substantial application implementation or download large model weights in this planning stage.** Planning documents and issue-backlog preparation are permitted.

After the plan is reviewed and approved, begin Phase 0 and implement each subsequent phase incrementally, applying TDD/BDD and updating the issue tracker and development journal.

Your first response should focus on the proposed architecture, important technical decisions, implementation risks, and the phased plan—not on generating a large amount of unreviewed application code.

**Success means a fully demonstrable homework application, a reproducible development environment, a well-understood implementation, and a genuine record of how the coding agent contributed to the engineering process.**