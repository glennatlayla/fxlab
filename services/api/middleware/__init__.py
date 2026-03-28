"""
API middleware for request/response processing.

Responsibilities:
- Enforce request size limits
- Rate limiting
- Correlation ID propagation

Does NOT:
- Contain business logic
- Store persistent state (all state is in-memory per process)
"""
