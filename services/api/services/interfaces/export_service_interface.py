"""
Export service interface — contract for data export service.

Responsibilities:
- Define the abstract interface for creating and managing export jobs.
- Specify contracts for export creation, retrieval, and download.
- Provide a clean boundary between the API routes and export implementation.

Does NOT:
- Contain implementation logic.
- Import concrete dependencies.
- Handle artifact storage directly (delegated to concrete implementations).

Dependencies:
- libs.contracts.export: ExportType, ExportStatus, ExportJobResponse.

Example:
    service: ExportServiceInterface = get_export_service()
    job = service.create_export(ExportType.TRADES, "01HRUN...", "01HUSER...", correlation_id="corr-123")
    bytes_data = service.download_export("01HEXPORT...", correlation_id="corr-123")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.export import ExportJobResponse, ExportType


class ExportServiceInterface(ABC):
    """
    Abstract interface for the export service.

    Implementations create export jobs, generate artifact bundles (zip files),
    persist jobs to a repository, store artifacts in durable storage, and
    support retrieval and download.

    Responsibilities:
    - Create new export jobs (async, state machine: PENDING → PROCESSING → COMPLETE/FAILED).
    - Retrieve export job status by ID.
    - List exports with optional filtering by requester or object ID.
    - Download completed export artifacts as raw bytes.
    - Generate export bundles (zip files with metadata, data, and README).

    Does NOT:
    - Know about HTTP request/response (that's the route layer).
    - Handle direct artifact storage operations (delegated to storage interface).
    - Validate business rules for export eligibility (caller responsibility).
    """

    @abstractmethod
    def create_export(
        self,
        export_type: ExportType,
        object_id: str,
        requested_by: str,
        *,
        correlation_id: str | None = None,
    ) -> ExportJobResponse:
        """
        Create a new export job and generate the artifact bundle.

        Follows the state machine: PENDING → PROCESSING → COMPLETE (or FAILED).
        Generates a zip bundle containing metadata.json, data files (CSV, JSON),
        and README.txt. Stores the bundle in artifact storage.

        Args:
            export_type: Type of export (TRADES, RUNS, ARTIFACTS).
            object_id: ULID of the resource being exported (run, candidate, artifact).
            requested_by: ULID of the user requesting the export.
            correlation_id: Optional request correlation ID for distributed tracing.

        Returns:
            ExportJobResponse with status=COMPLETE and artifact_uri set on success.
            On failure, returns job with status=FAILED and error_message set.

        Raises:
            ExternalServiceError: If artifact storage fails (wrapped, not swallowed).

        Example:
            job = service.create_export(
                ExportType.TRADES,
                "01HRUN0ABCD1234567890ABCD",
                "01HUSER0XYZW987654321XYZW",
                correlation_id="corr-req-001"
            )
            # Returns: ExportJobResponse(id="01HEXPORT...", status=COMPLETE, artifact_uri="exports/01HEXPORT....zip")
        """

    @abstractmethod
    def get_export(self, job_id: str) -> ExportJobResponse | None:
        """
        Retrieve an export job by ID.

        Args:
            job_id: The ULID of the export job.

        Returns:
            The ExportJobResponse if found, None otherwise.

        Example:
            job = service.get_export("01HEXPORT0ABCD1234567890ABCD")
            if job and job.status == ExportStatus.COMPLETE:
                print(f"Download at {job.artifact_uri}")
        """

    @abstractmethod
    def list_exports(
        self,
        *,
        requested_by: str | None = None,
        object_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ExportJobResponse], int]:
        """
        List exports with optional filters and pagination.

        If both requested_by and object_id are provided, filters on both.
        Exactly one of requested_by or object_id may be None.

        Args:
            requested_by: Optional ULID of user who requested the export (filters if provided).
            object_id: Optional ULID of exported object (filters if provided).
            limit: Max number of jobs to return (default 50).
            offset: Pagination offset (default 0).

        Returns:
            Tuple of (list of ExportJobResponse, total count of matching jobs).

        Example:
            jobs, total = service.list_exports(requested_by="01HUSER0XYZ...", limit=10)
            print(f"Fetched {len(jobs)} of {total} total exports")
        """

    @abstractmethod
    def download_export(self, job_id: str, *, correlation_id: str | None = None) -> bytes:
        """
        Download the export artifact as raw bytes.

        The export must be in COMPLETE status with a valid artifact_uri
        set. Calls the underlying artifact storage to retrieve the zip.

        Args:
            job_id: The ULID of the export job.
            correlation_id: Optional request correlation ID for distributed tracing.

        Returns:
            Raw bytes of the export zip file.

        Raises:
            NotFoundError: If the job does not exist.
            NotFoundError: If the job is not in COMPLETE status (no artifact_uri).
            FileNotFoundError: If the artifact file is missing from storage.
            ExternalServiceError: If the storage backend is unreachable.

        Example:
            try:
                zip_bytes = service.download_export("01HEXPORT0ABCD1234567890ABCD")
                with open("export.zip", "wb") as f:
                    f.write(zip_bytes)
            except NotFoundError:
                print("Export not found or not yet complete")
        """
