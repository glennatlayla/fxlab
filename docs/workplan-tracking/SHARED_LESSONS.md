# FXLab Shared Lessons (cross-phase)
# Promote lessons here when Apply-to spans 2+ phases.
# Last updated: 2026-03-27T12:30:00Z
#
# Format:
#   LL-SNNN  Title
#   Source workplan + ISS ref
#   Lesson text
#   Apply to: All phases / Phase N+

---
# LL-S001
# Title:     SQLAlchemy DeclarativeBase reserves 'metadata' as a class attribute
# Milestone: M2 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / ISS-001
# Lesson:    Never name a SQLAlchemy model column 'metadata'.  DeclarativeBase
#            (SQLAlchemy 2.x) exposes cls.metadata as the MetaData object; a
#            column of that name raises InvalidRequestError at class definition
#            time.  Rename the Python attribute (e.g. event_metadata) and use
#            Column("metadata", ...) to preserve the DB column name.
# Apply to:  All phases that define SQLAlchemy ORM models

---
# LL-S002
# Title:     Accumulator pattern must preserve @pytest.fixture decorators
# Milestone: M2 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / ISS-003
# Lesson:    When merging or regenerating conftest.py via an accumulator
#            approach, always verify that every fixture function retains the
#            @pytest.fixture decorator.  Plain function definitions are invisible
#            to pytest.  Prefer a full rewrite over incremental appending to
#            avoid silent omissions.
# Apply to:  All phases that maintain conftest.py files

---
# LL-S003
# Title:     Hand-crafted ULID test values must be counted to exactly 26 chars
# Milestone: M2 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / ISS-004
# Lesson:    ULIDs are exactly 26 Crockford Base32 characters.  When writing
#            test ULIDs by hand, use: prefix(4) + padding(22) = 26.  The common
#            error is 4 + 23 = 27.  Example valid: "01HQAAAAAAAAAAAAAAAAAAAAAA".
# Apply to:  All phases that declare hand-crafted test ULIDs

---
# LL-S004
# Title:     SQLAlchemy integration tests need SAVEPOINT isolation with shared engines
# Milestone: M2 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / ISS-005
# Lesson:    With a module-scoped engine and per-test sessions, wrap each test
#            in a SAVEPOINT (connection.begin_nested()) so test data rolls back
#            after each test.  Use session.flush() not session.commit() inside
#            fixtures to avoid committing past the SAVEPOINT boundary.
#            Full pattern:
#              connection = engine.connect()
#              transaction = connection.begin()
#              session = Session(bind=connection)
#              nested = connection.begin_nested()
#              yield session
#              session.close(); nested.rollback(); transaction.rollback(); connection.close()
# Apply to:  All phases with SQLAlchemy-backed integration tests

---
# LL-S005
# Title:     Maintain issues and lessons files in real-time during each milestone
# Milestone: M3 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / meta-review
# Lesson:    Issues and lessons files should be updated as issues are found, not
#            retroactively in a meta-review session.  Workflow per issue:
#            (1) Log in .issues immediately when discovered.
#            (2) Add to .lessons-learned when resolved.
#            (3) Promote to SHARED_LESSONS.md if applicable across 2+ phases.
#            Deferring this work compounds debt and risks losing the details.
# Apply to:  All phases, all milestones

---
# LL-S007 (promoted from LL-008)
# Title:     FastAPI response_model serialization fails with pydantic-core stub; use explicit JSONResponse
# Milestone: M5 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / M5-S4
# Lesson:    When pydantic-core native binary is absent (cross-arch sandbox or any
#            env where the .so cannot load), FastAPI's response_model= serialization
#            silently returns {} instead of raising.  Three-part workaround for all
#            FastAPI route handlers that return Pydantic models:
#            (1) Remove response_model= from the decorator.
#            (2) Return JSONResponse(content=model.model_dump(...)) explicitly.
#            (3) Use model_construct() instead of Model() for any model with
#                Optional[str] fields, and add explicit int() coercion for numeric
#                query params since model_construct bypasses type coercion.
#            This workaround is safe in production — it produces identical output
#            to the pydantic-core path but is deterministic across architectures.
# Apply to:  All phases — any milestone adding FastAPI routes that return Pydantic models

---
# LL-S008 (promoted from LL-009)
# Title:     ruff and mypy wheel binaries are arch-specific; cannot run in cross-arch sandbox
# Milestone: M5 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / M5-S5
# Lesson:    Wheels installed for macOS arm64 (the dev host) contain compiled .so
#            extension modules that cannot execute on Linux x86_64 (the sandbox VM).
#            The OS returns "Exec format error".  This affects ruff, mypy, and any
#            other tool with native extensions.  Static analysis must be run on the
#            host machine.  In the sandbox: use python ast.parse() for syntax
#            validation, black --fast for formatting, and pytest --cov for coverage.
#            Document in team CI: the sandbox is not a substitute for host-side
#            type checking and lint; these gates must run in a native CI runner.
# Apply to:  All phases — inform CI setup for any milestone using cross-arch sandboxing

---
# LL-S009 (promoted from LL-010)
# Title:     FastAPI int Query() params arrive as str when pydantic-core coercion is absent
# Milestone: M6 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / ISS-015
# Lesson:    Default Query() int values (Python literals) are unaffected, but values
#            supplied in the HTTP query string (e.g. ?offset=1) arrive as str when
#            pydantic-core cannot coerce them.  Always add explicit int() casts in
#            route handlers before forwarding numeric params to service/repository
#            calls: repo.list(limit=int(limit), offset=int(offset), ...).
#            This is a specialisation of LL-S007 and applies to ALL FastAPI endpoints
#            that accept numeric query parameters in any cross-arch sandbox.
# Apply to:  All phases — any route handler that accepts numeric Query() parameters

---
# LL-S010 (promoted from LL-011)
# Title:     str-enum model_dump() defensive guards are logically unreachable
# Milestone: M6 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / M6-S5
# Lesson:    When a Pydantic field is a str-enum, model_dump() already serializes it
#            to the string value.  Guards of the form:
#                if hasattr(raw["field"], "value"): raw["field"] = raw["field"].value
#            will never execute.  Mark them with # pragma: no cover rather than
#            writing artificial tests.  This applies to ALL serialization helpers
#            in route handlers across all phases.
# Apply to:  All phases — any serialization helper that handles str-enum fields

---
# LL-S011 (promoted from LL-012)
# Title:     Optional[str-Enum] Pydantic field fails in cross-arch stub when value is non-None
# Milestone: M7 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / M7-S4
# Lesson:    pydantic-core cross-arch stub raises:
#            "TypeError: typing.Optional[...SomeEnum] is not a generic class"
#            specifically when an Optional[str-Enum] field is assigned a NON-None value.
#            Optional[str-Enum] = None passes silently; Optional[str-Enum] = Enum.VALUE fails.
#            This extends LL-S007 (which covered Optional[str]) to Optional[Enum] subclasses.
#            Fix: use model_construct() instead of Model(**kwargs) for any Pydantic model
#            that contains an Optional[Enum] field that may be populated with a non-None value:
#                return MyModel.model_construct(optional_enum_field=SomeEnum.VALUE, ...)
#            When the field is always None (no-sampling path), normal construction works;
#            the bug surfaces only when LTTB/sampling is applied (non-None enum path).
# Apply to:  All phases — any Pydantic model with Optional[Enum] fields in cross-arch sandbox

---
# LL-S012 (promoted from LL-013)
# Title:     Update BOTH unit AND integration tests when an API endpoint shape changes
# Milestone: M9 (Phase 3)
# Source:    FXLab_Phase_3_workplan_v1_1 / M9-S5 QUALITY GATE
# Lesson:    When M7 changed GET /queues/contention (aggregate) to GET /queues/{queue_class}/contention
#            (per-class), the unit tests in test_jobs.py were correctly updated (ISS-018).
#            However, the integration tests in test_m4_jobs_queues.py::TestQueuesContentionEndpointIntegration
#            were NOT updated. This was not caught until the M9 full-suite quality gate, where
#            4 integration tests failed with 404 assertions.
#            Fix protocol: When changing or removing an API endpoint:
#            1. grep -r "old_endpoint_path" tests/ -- find ALL affected test files.
#            2. Update unit tests (test_*.py in tests/unit/).
#            3. Update integration tests (test_*.py in tests/integration/).
#            4. Run the FULL test suite (not just the unit test subset) before closing the milestone.
# Apply to:  All phases — any API endpoint shape or routing change
