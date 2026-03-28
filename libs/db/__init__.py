"""
Database abstractions and repository implementations.
Provides metadata database interface and SQLAlchemy-based implementations.
"""

from libs.db.metadata import MetadataDatabase

__all__ = ["MetadataDatabase"]
