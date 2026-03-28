<<<<<<< HEAD
# FXLab Phase 3 — Web UX, Governance, and Results/Export Surfaces

## Overview

Phase 3 implements the web UX layer on top of Phase 1 (operational infrastructure) and 
Phase 2 (research/compiler/readiness APIs). This provides non-technical operators with:

- Strategy draft authoring with autosave
- Optimization monitoring and trial inspection
- Readiness report review with blocker detail
- Promotion request submission and governance tracking
- Override visibility across all surfaces
- Feed health monitoring
- Export surfaces with lineage metadata
- Artifact, audit, and queue browsing

## Architecture

```
services/
├── api/              # FastAPI application layer (routes, models)
├── domain/           # Business logic (services, use cases)
└── infrastructure/   # External systems (database, storage, queues)

tests/
├── api/              # API endpoint tests
├── domain/           # Business logic tests
└── integration/      # Cross-layer integration tests
```

## Development Setup

### Prerequisites

- Python 3.11+
- pip or uv

### Installation

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt
```

### Running Tests

```bash
# Run full test suite with coverage
pytest

# Run specific test file
pytest tests/api/test_main.py

# Run with verbose output
pytest -v

# Generate HTML coverage report
pytest --cov-report=html
open htmlcov/index.html
```

### Code Quality

```bash
# Format code
ruff format .

# Lint code
ruff check .

# Type check
mypy services/
```

### Running the API

```bash
# Development server with auto-reload
uvicorn services.api.main:app --reload

# Production server
uvicorn services.api.main:app --host 0.0.0.0 --port 8000
```

API will be available at:
- http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Alternative docs: http://localhost:8000/redoc

## Quality Standards

All code must pass:
- **Formatting:** `ruff format --check .`
- **Linting:** `ruff check .`
- **Type checking:** `mypy services/`
- **Tests:** `pytest` with >= 80% coverage overall, >= 85% new code, >= 90% services

## Non-Negotiable Rules

1. No business logic in controllers
2. All mutations map to auditable backend actions
3. Override state visible everywhere relevant
4. Exports are zip bundles with lineage metadata
5. Blockers include owner and next step
6. Draft work is never silently discarded
7. High-density charts are downsampled server-side
8. Governance evidence links are required URIs

See `docs/ARCHITECTURE.md` for detailed design decisions.

## Project Status

**Current Phase:** Bootstrap (M0)  
**Version:** 0.1.0-bootstrap

## License

Proprietary - Internal Use Only
=======
# fxlab
>>>>>>> 5511e60521cc6152eec611323f7d78237cf69900
