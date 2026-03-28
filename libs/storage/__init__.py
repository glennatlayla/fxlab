"""
Storage layer providing object storage abstraction for artifacts.

Canonical base class: ArtifactStorageBase (libs.storage.base)

The name ArtifactStorage is preserved for backward compatibility.
New code should import ArtifactStorageBase directly.
"""

from libs.storage.artifact_storage import ArtifactStorage  # backward compat alias
from libs.storage.base import ArtifactStorageBase
from libs.storage.local_storage import LocalArtifactStorage

__all__ = [
    "ArtifactStorage",  # legacy alias — prefer ArtifactStorageBase
    "ArtifactStorageBase",
    "LocalArtifactStorage",
]
