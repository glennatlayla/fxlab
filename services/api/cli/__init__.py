"""
CLI tools for the FXLab API service.

Purpose:
    Package for command-line utilities that operate on the FXLab database
    directly (e.g. seeding, migrations, maintenance). Each module is
    runnable via ``python -m services.api.cli.<module>``.

Does NOT:
    - Contain business logic (delegates to service/repository layers).
    - Replace API endpoints (these are operator-only maintenance tools).
"""
