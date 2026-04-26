"""
Command-line entry points for FXLab.

Each module under :mod:`services.cli` is invokable with
``python -m services.cli.<module>``. The CLIs are thin
orchestration shells that wire together the same domain
services used by the API and worker layers; they own no
business logic of their own.
"""
