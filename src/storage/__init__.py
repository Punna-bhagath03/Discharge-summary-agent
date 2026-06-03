"""
Public API for src/storage.

All other phases import from src.storage rather than from the submodule
directly.  This ensures that the storage contract (the public method
signatures on StorageService) is the only surface other components depend
on, keeping the backend replaceable as required by NFR-8.
"""

from src.storage.storage_service import (
    EvidenceAlreadyExistsError,
    PatientAlreadyExistsError,
    ReviewFlagAlreadyExistsError,
    StorageError,
    StorageService,
)

__all__ = [
    "StorageService",
    # Exceptions — exported so callers can catch specific errors
    # without importing from the submodule directly.
    "StorageError",
    "PatientAlreadyExistsError",
    "EvidenceAlreadyExistsError",
    "ReviewFlagAlreadyExistsError",
]
