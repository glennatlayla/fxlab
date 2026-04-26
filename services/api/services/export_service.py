"""
Export service — creates and manages export jobs for trading data, runs, and artifacts.

Responsibilities:
- Create export jobs and drive them through the state machine (PENDING → PROCESSING → COMPLETE/FAILED).
- Generate export bundles (zip files) containing data files (CSV, JSON) and metadata.
- Persist jobs using the ExportRepositoryInterface.
- Store artifact bundles using the ArtifactStorageBase.
- Retrieve and list export jobs.
- Download completed export artifacts.
- Structured logging for all operations.

Does NOT:
- Handle HTTP request/response (that's the route layer).
- Validate business rules for export eligibility (caller responsibility).
- Perform any authentication or authorization (that's the controller layer).

Dependencies:
- libs.contracts.interfaces.export_repository_interface.ExportRepositoryInterface: job persistence.
- libs.storage.base.ArtifactStorageBase: artifact storage backend.
- libs.contracts.export: ExportType, ExportStatus, ExportJobResponse.
- libs.contracts.errors: NotFoundError, ExternalServiceError.
- structlog: structured logging.
- ulid: ULID generation for job IDs.
- zipfile, io, json: artifact bundle generation.

Error conditions:
- Storage failure (I/O, network) → update job to FAILED, log, re-raise ExternalServiceError.
- Job not found on get/download → raise NotFoundError.
- Job incomplete on download → raise NotFoundError.

Example:
    service = ExportService(repo=repo, storage=storage)
    job = service.create_export(ExportType.TRADES, "01HRUN...", "01HUSER...", correlation_id="corr-123")
    # job.status == COMPLETE, artifact_uri == "exports/01HEXPORT....zip"
    bytes_data = service.download_export(job.id, correlation_id="corr-123")
"""

from __future__ import annotations

import csv
import io
import json
import time
import zipfile
from collections import defaultdict, deque
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal

import structlog
import ulid as _ulid

from libs.contracts.backtest import BacktestTrade
from libs.contracts.errors import ExternalServiceError, NotFoundError
from libs.contracts.export import ExportJobResponse, ExportStatus, ExportType
from libs.contracts.interfaces.export_repository_interface import (
    ExportRepositoryInterface,
)
from libs.contracts.interfaces.research_run_repository import (
    ResearchRunRepositoryInterface,
)
from libs.contracts.research_run import ResearchRunStatus
from libs.contracts.run_results import (
    RUN_BLOTTER_CSV_COLUMNS,
    RUN_BLOTTER_EXPORT_CHUNK_SIZE,
    TradeBlotterRow,
)
from libs.storage.base import ArtifactStorageBase
from services.api.middleware.correlation import correlation_id_var
from services.api.services.interfaces.export_service_interface import (
    ExportServiceInterface,
)
from services.api.services.research_run_service import RunNotCompletedError

logger = structlog.get_logger(__name__)


class ExportService(ExportServiceInterface):
    """
    Production export service for trading data, runs, and artifacts.

    Manages the full lifecycle of export jobs:
    1. Create job with PENDING status.
    2. Update to PROCESSING.
    3. Generate export bundle (zip with metadata, data files, README).
    4. Store bundle in artifact storage.
    5. Update to COMPLETE with artifact URI.
    6. On error: update to FAILED with error message and re-raise.

    Bundles are zip files with the following structure:
    - metadata.json: {"export_type": "...", "object_id": "...", "exported_at": "...", "requested_by": "..."}
    - README.txt: Simple description of the export.
    - data.csv or results.json: Type-specific data file (TRADES → CSV, RUNS → JSON, ARTIFACTS → none).

    Responsibilities:
    - Create new export jobs and drive state transitions.
    - Generate export bundles using in-memory zip construction.
    - Persist jobs to a repository interface.
    - Store artifacts to a storage backend.
    - Retrieve and list jobs.
    - Download completed artifacts.

    Does NOT:
    - Contain business logic for what data to export (stub data for proof-of-concept).
    - Handle HTTP concerns.
    - Validate export eligibility.

    Dependencies:
    - ExportRepositoryInterface: job persistence.
    - ArtifactStorageBase: artifact storage.
    - structlog: structured logging.

    Example:
        service = ExportService(repo=repo, storage=storage)
        job = service.create_export(ExportType.TRADES, object_id="...", requested_by="...")
        bytes_data = service.download_export(job.id)
    """

    def __init__(
        self,
        repo: ExportRepositoryInterface,
        storage: ArtifactStorageBase,
        *,
        research_run_repo: ResearchRunRepositoryInterface | None = None,
    ) -> None:
        """
        Initialize the export service.

        Args:
            repo: ExportRepositoryInterface for job persistence.
            storage: ArtifactStorageBase for artifact storage.
            research_run_repo: Optional ResearchRunRepositoryInterface used by
                :meth:`stream_run_blotter_csv` to look up the source run record
                for a CSV blotter export. ``None`` keeps existing call sites
                that only need the job-bundle path working unchanged; the
                streamer raises ``RuntimeError`` when invoked without it.
        """
        self._repo = repo
        self._storage = storage
        self._research_run_repo = research_run_repo

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
        and README.txt. Stores the bundle in artifact storage under bucket="exports".

        Args:
            export_type: Type of export (TRADES, RUNS, ARTIFACTS).
            object_id: ULID of the resource being exported.
            requested_by: ULID of the user requesting the export.
            correlation_id: Optional request correlation ID for distributed tracing.

        Returns:
            ExportJobResponse with status=COMPLETE and artifact_uri set.

        Raises:
            ExternalServiceError: If storage or repository fails (wrapped).

        Example:
            job = service.create_export(
                ExportType.TRADES,
                "01HRUN0ABCD1234567890ABCD",
                "01HUSER0XYZW987654321XYZW",
                correlation_id="corr-req-001"
            )
        """
        t0 = time.monotonic()
        job_id = str(_ulid.ULID())
        now = datetime.now(timezone.utc)

        try:
            # Step 1: Create PENDING job
            pending_job = ExportJobResponse(
                id=job_id,
                export_type=export_type,
                object_id=object_id,
                status=ExportStatus.PENDING,
                artifact_uri=None,
                requested_by=requested_by,
                error_message=None,
                created_at=now,
                updated_at=now,
                override_watermark=None,
            )
            self._repo.create_job(pending_job)

            logger.info(
                "export.job_created",
                operation="export_create",
                component="ExportService",
                job_id=job_id,
                export_type=export_type.value,
                object_id=object_id,
                requested_by=requested_by,
                correlation_id=correlation_id,
                result="success",
            )

            # Step 2: Update to PROCESSING
            self._repo.update_job(
                job_id,
                status=ExportStatus.PROCESSING,
            )

            logger.debug(
                "export.job_processing",
                operation="export_create",
                component="ExportService",
                job_id=job_id,
                correlation_id=correlation_id,
            )

            # Step 3: Generate export bundle
            bundle_bytes = self._generate_bundle(export_type, object_id, requested_by, now)

            # Step 4: Store bundle in artifact storage
            storage_key = f"{job_id}.zip"
            artifact_uri = self._storage.put(
                data=bundle_bytes,
                bucket="exports",
                key=storage_key,
                metadata={
                    "export_type": export_type.value,
                    "object_id": object_id,
                    "requested_by": requested_by,
                    "correlation_id": correlation_id or "",
                },
                correlation_id=correlation_id,
            )

            logger.debug(
                "export.bundle_stored",
                operation="export_create",
                component="ExportService",
                job_id=job_id,
                artifact_uri=artifact_uri,
                bundle_size_bytes=len(bundle_bytes),
                correlation_id=correlation_id,
            )

            # Step 5: Update to COMPLETE with artifact URI
            completed_job = self._repo.update_job(
                job_id,
                status=ExportStatus.COMPLETE,
                artifact_uri=artifact_uri,
            )

            duration_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "export.job_complete",
                operation="export_create",
                component="ExportService",
                job_id=job_id,
                export_type=export_type.value,
                artifact_uri=artifact_uri,
                duration_ms=round(duration_ms, 2),
                correlation_id=correlation_id,
                result="success",
            )

            return completed_job

        except (OSError, Exception) as exc:
            # Step 5b: On error, update to FAILED with error message
            error_msg = f"{type(exc).__name__}: {str(exc)}"

            try:
                self._repo.update_job(
                    job_id,
                    status=ExportStatus.FAILED,
                    error_message=error_msg,
                )

                logger.error(
                    "export.job_failed",
                    operation="export_create",
                    component="ExportService",
                    job_id=job_id,
                    export_type=export_type.value,
                    error=str(exc),
                    correlation_id=correlation_id,
                    result="failure",
                    exc_info=True,
                )

            except Exception as update_exc:
                # If update fails, log it but still raise the original error
                logger.error(
                    "export.job_update_failed",
                    operation="export_create",
                    component="ExportService",
                    job_id=job_id,
                    error=str(update_exc),
                    correlation_id=correlation_id,
                    exc_info=True,
                )

            # Re-raise as ExternalServiceError
            raise ExternalServiceError(f"Export creation failed: {error_msg}") from exc

    def get_export(self, job_id: str) -> ExportJobResponse | None:
        """
        Retrieve an export job by ID.

        Args:
            job_id: The ULID of the export job.

        Returns:
            The ExportJobResponse if found, None otherwise.

        Example:
            job = service.get_export("01HEXPORT0ABCD1234567890ABCD")
            if job:
                print(f"Status: {job.status}, URI: {job.artifact_uri}")
        """
        job = self._repo.get_job(job_id)

        if job:
            logger.debug(
                "export.job_retrieved",
                operation="export_get",
                component="ExportService",
                job_id=job_id,
                status=job.status.value,
            )
        else:
            logger.debug(
                "export.job_not_found",
                operation="export_get",
                component="ExportService",
                job_id=job_id,
            )

        return job

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

        If object_id is provided, uses list_by_object_id.
        Otherwise, uses list_jobs with optional requested_by filter.

        Args:
            requested_by: Optional ULID of requesting user (filters if provided).
            object_id: Optional ULID of exported object (filters if provided).
            limit: Max number of jobs to return (default 50).
            offset: Pagination offset (default 0).

        Returns:
            Tuple of (list of ExportJobResponse, total count).

        Example:
            jobs, total = service.list_exports(requested_by="01HUSER0XYZ...", limit=10)
            print(f"Returned {len(jobs)} of {total} total")
        """
        if object_id:
            jobs, total = self._repo.list_by_object_id(object_id, limit=limit, offset=offset)
        else:
            jobs, total = self._repo.list_jobs(
                requested_by=requested_by, limit=limit, offset=offset
            )

        logger.debug(
            "export.jobs_listed",
            operation="export_list",
            component="ExportService",
            requested_by=requested_by,
            object_id=object_id,
            limit=limit,
            offset=offset,
            returned=len(jobs),
            total=total,
        )

        return jobs, total

    def download_export(self, job_id: str, *, correlation_id: str | None = None) -> bytes:
        """
        Download the export artifact as raw bytes.

        The export must be in COMPLETE status with a valid artifact_uri.
        Calls the underlying artifact storage to retrieve the zip.

        Args:
            job_id: The ULID of the export job.
            correlation_id: Optional request correlation ID for distributed tracing.

        Returns:
            Raw bytes of the export zip file.

        Raises:
            NotFoundError: If the job does not exist.
            NotFoundError: If the job is not in COMPLETE status.
            FileNotFoundError: If the artifact is missing from storage.
            ExternalServiceError: If storage backend is unreachable.

        Example:
            zip_bytes = service.download_export("01HEXPORT0ABCD1234567890ABCD")
            with open("export.zip", "wb") as f:
                f.write(zip_bytes)
        """
        job = self._repo.get_job(job_id)
        if not job:
            logger.warning(
                "export.download_not_found",
                operation="export_download",
                component="ExportService",
                job_id=job_id,
                correlation_id=correlation_id,
            )
            raise NotFoundError(f"Export job {job_id} not found")

        if job.status != ExportStatus.COMPLETE or not job.artifact_uri:
            logger.warning(
                "export.download_incomplete",
                operation="export_download",
                component="ExportService",
                job_id=job_id,
                status=job.status.value,
                artifact_uri=job.artifact_uri,
                correlation_id=correlation_id,
            )
            raise NotFoundError(f"Export job {job_id} is not complete or has no artifact URI")

        try:
            # Parse bucket and key from artifact_uri (format: "bucket/key")
            parts = job.artifact_uri.split("/", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid artifact URI format: {job.artifact_uri}")
            bucket, key = parts

            artifact_bytes = self._storage.get(
                bucket=bucket,
                key=key,
                correlation_id=correlation_id or "",
            )

            logger.info(
                "export.downloaded",
                operation="export_download",
                component="ExportService",
                job_id=job_id,
                artifact_size_bytes=len(artifact_bytes),
                correlation_id=correlation_id,
                result="success",
            )

            return artifact_bytes

        except FileNotFoundError:
            logger.error(
                "export.artifact_missing",
                operation="export_download",
                component="ExportService",
                job_id=job_id,
                artifact_uri=job.artifact_uri,
                correlation_id=correlation_id,
            )
            raise

        except Exception as exc:
            logger.error(
                "export.download_failed",
                operation="export_download",
                component="ExportService",
                job_id=job_id,
                artifact_uri=job.artifact_uri,
                error=str(exc),
                correlation_id=correlation_id,
                exc_info=True,
            )
            raise ExternalServiceError(f"Failed to download export {job_id}: {str(exc)}") from exc

    # -----------------------------------------------------------------------
    # Run-blotter CSV streaming
    # -----------------------------------------------------------------------

    def stream_run_blotter_csv(self, run_id: str) -> Iterator[bytes]:
        """
        Stream the round-trip trade blotter for a completed run as CSV bytes.

        Lifts :class:`BacktestTrade` legs out of the run's
        :class:`BacktestResult`, pairs them into FIFO round-trips per
        symbol (opening side -> matching opposite-side close), and yields
        UTF-8 CSV bytes in chunks of at most :data:`RUN_BLOTTER_EXPORT_CHUNK_SIZE`
        rows so memory stays bounded for runs with very large blotters.

        The first yielded chunk always begins with the canonical header
        row (:data:`RUN_BLOTTER_CSV_COLUMNS`). Subsequent chunks contain
        only data rows.

        Round-trip pairing rules (FIFO per symbol):

            * Opening leg = first leg seen on a symbol whose remaining
              position is zero. ``side`` of the round-trip mirrors the
              opening leg ('buy' for long, 'sell' for short).
            * Closing leg = next leg with the opposite side on the same
              symbol that fully matches the opening leg's quantity. The
              implementation assumes the engine emits balanced legs, which
              the synthetic backtest executor in ``services/api/services/
              synthetic_backtest_executor.py`` and the M2.D5 walk-forward
              path both honour.
            * Realised PnL: long round-trip ->
              ``(exit_price - entry_price) * units - fees``;
              short round-trip ->
              ``(entry_price - exit_price) * units - fees``.
            * Fees aggregate ``commission + slippage`` across both legs.
            * Holding-period seconds: ``(exit_time - entry_time).total_seconds()``
              cast to ``int``.
            * Open positions at run end (no matching closing leg) surface
              with empty ``exit_time`` / ``exit_price`` / ``realized_pnl`` /
              ``holding_period_seconds`` cells; ``fees`` covers only the
              opening leg.

        Args:
            run_id: ULID of the research run to export.

        Yields:
            UTF-8-encoded CSV byte chunks. The first chunk begins with the
            header row; subsequent chunks are pure data rows. Each chunk
            contains at most :data:`RUN_BLOTTER_EXPORT_CHUNK_SIZE` rows.

        Raises:
            RuntimeError: If the service was constructed without a
                ``research_run_repo`` dependency.
            NotFoundError: If no run record exists for ``run_id``.
            RunNotCompletedError: If the run exists but is not in
                terminal COMPLETED status with a result body.

        Example:
            >>> for chunk in service.stream_run_blotter_csv("01HRUN..."):
            ...     response_body.write(chunk)
        """
        if self._research_run_repo is None:
            raise RuntimeError(
                "ExportService.stream_run_blotter_csv requires a "
                "research_run_repo dependency; pass one to ExportService(...)."
            )

        t0 = time.monotonic()
        correlation_id = correlation_id_var.get("no-corr")

        record = self._research_run_repo.get_by_id(run_id)
        if record is None:
            logger.warning(
                "run_blotter_export.not_found",
                operation="run_blotter_export",
                component="ExportService",
                run_id=run_id,
                correlation_id=correlation_id,
            )
            raise NotFoundError(f"Research run {run_id} not found")

        if record.status != ResearchRunStatus.COMPLETED or record.result is None:
            logger.warning(
                "run_blotter_export.not_completed",
                operation="run_blotter_export",
                component="ExportService",
                run_id=run_id,
                run_status=record.status.value,
                correlation_id=correlation_id,
            )
            raise RunNotCompletedError(run_id, record.status)

        backtest_result = record.result.backtest_result
        legs: list[BacktestTrade] = (
            list(backtest_result.trades) if backtest_result is not None else []
        )

        logger.info(
            "run_blotter_export_started",
            operation="run_blotter_export",
            component="ExportService",
            run_id=run_id,
            requested_by=record.created_by,
            leg_count=len(legs),
            correlation_id=correlation_id,
        )

        rows = self._pair_trades_into_round_trips(legs)
        row_count = 0

        # Yield in chunks. Each chunk is a single bytes object that may
        # carry multiple CSV lines. We use csv.writer over an in-memory
        # text buffer so the CSV escaping rules (quoting, embedded commas)
        # match the standard library's behaviour exactly.
        def _flush(buffer: io.StringIO) -> bytes:
            payload = buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)
            return payload

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")

        # Header row is always the first chunk.
        writer.writerow(RUN_BLOTTER_CSV_COLUMNS)
        yield _flush(buffer)

        rows_in_chunk = 0
        for row in rows:
            writer.writerow(self._format_row_for_csv(row))
            rows_in_chunk += 1
            row_count += 1
            if rows_in_chunk >= RUN_BLOTTER_EXPORT_CHUNK_SIZE:
                yield _flush(buffer)
                rows_in_chunk = 0

        if rows_in_chunk > 0:
            yield _flush(buffer)

        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "run_blotter_export_completed",
            operation="run_blotter_export",
            component="ExportService",
            run_id=run_id,
            row_count=row_count,
            duration_ms=round(duration_ms, 2),
            correlation_id=correlation_id,
            result="success",
        )

    @staticmethod
    def _pair_trades_into_round_trips(
        legs: list[BacktestTrade],
    ) -> list[TradeBlotterRow]:
        """
        Pair execution legs into round-trip :class:`TradeBlotterRow` rows.

        Per-symbol FIFO pairing:
            * The first leg seen on a symbol whose net position is zero
              opens a new round-trip.
            * The next leg on the same symbol whose side is opposite to
              the open round-trip's opening side closes it. Sequential
              same-side legs accumulate as additional opens (still FIFO).
            * Trade rows are deterministically sorted by entry_time so the
              CSV is byte-identical across repeated invocations.

        Args:
            legs: All :class:`BacktestTrade` legs from the run, in engine
                emission order.

        Returns:
            All round-trip rows (closed and still-open) sorted by
            ``entry_time`` ascending.
        """
        # Process legs in stable engine order. ``open_legs`` is a per-symbol
        # FIFO of unmatched openings; each entry carries the ULID-style
        # ``trade_id`` derived from the leg's index into the input list so
        # the identifier is stable across runs.
        open_legs: dict[str, deque[tuple[int, BacktestTrade]]] = defaultdict(deque)
        closed_rows: list[TradeBlotterRow] = []

        for index, leg in enumerate(legs):
            queue = open_legs[leg.symbol]
            if not queue:
                queue.append((index, leg))
                continue

            head_index, head_leg = queue[0]
            if head_leg.side == leg.side:
                # Same-side stack: accumulate as another open leg.
                queue.append((index, leg))
                continue

            # Opposite side -> close the head opening leg. We assume the
            # engine emits a matching closing-quantity leg; we use the
            # opening leg's quantity as the round-trip ``units`` (the
            # closing leg's quantity is checked via the sign-only PnL
            # math, not enforced as equal here because some engines emit
            # partial closes that the v1 export collapses into the head).
            queue.popleft()
            closed_rows.append(
                ExportService._build_round_trip_row(
                    open_index=head_index,
                    open_leg=head_leg,
                    close_leg=leg,
                )
            )

        # Anything left in the per-symbol queues at the end is an open
        # position at run end. Surface as still-open rows so consumers see
        # exposure that was carried over the run boundary.
        for queue in open_legs.values():
            for open_index, open_leg in queue:
                closed_rows.append(
                    ExportService._build_round_trip_row(
                        open_index=open_index,
                        open_leg=open_leg,
                        close_leg=None,
                    )
                )

        closed_rows.sort(key=lambda r: (r.entry_time, r.trade_id))
        return closed_rows

    @staticmethod
    def _build_round_trip_row(
        *,
        open_index: int,
        open_leg: BacktestTrade,
        close_leg: BacktestTrade | None,
    ) -> TradeBlotterRow:
        """
        Project an (open, close) leg pair into a :class:`TradeBlotterRow`.

        Args:
            open_index: Position of the opening leg in the engine's
                trade list. Used to derive the stable ``trade_id``.
            open_leg: Opening execution leg.
            close_leg: Matching closing leg, or ``None`` for still-open
                positions at run end.

        Returns:
            A frozen :class:`TradeBlotterRow` describing the round-trip.
        """
        trade_id = f"trade-{open_index:06d}"
        units = open_leg.quantity
        entry_price = open_leg.price
        open_fees = open_leg.commission + open_leg.slippage

        if close_leg is None:
            return TradeBlotterRow(
                trade_id=trade_id,
                symbol=open_leg.symbol,
                side=open_leg.side,
                entry_time=open_leg.timestamp,
                exit_time=None,
                units=units,
                entry_price=entry_price,
                exit_price=None,
                fees=open_fees,
                realized_pnl=None,
                holding_period_seconds=None,
            )

        close_fees = close_leg.commission + close_leg.slippage
        total_fees = open_fees + close_fees
        exit_price = close_leg.price

        if open_leg.side == "buy":
            realized = (exit_price - entry_price) * units - total_fees
        else:
            realized = (entry_price - exit_price) * units - total_fees

        holding = int((close_leg.timestamp - open_leg.timestamp).total_seconds())

        return TradeBlotterRow(
            trade_id=trade_id,
            symbol=open_leg.symbol,
            side=open_leg.side,
            entry_time=open_leg.timestamp,
            exit_time=close_leg.timestamp,
            units=units,
            entry_price=entry_price,
            exit_price=exit_price,
            fees=total_fees,
            realized_pnl=realized,
            holding_period_seconds=holding,
        )

    @staticmethod
    def _format_row_for_csv(row: TradeBlotterRow) -> list[str]:
        """
        Serialise a :class:`TradeBlotterRow` into the CSV column order.

        Decimal fields use ``str(Decimal)`` so the wire format mirrors
        the JSON blotter endpoint's representation. ``None`` cells
        surface as empty strings so spreadsheet importers can detect
        still-open positions without parsing magic sentinels.
        """

        def _fmt_decimal(value: Decimal | None) -> str:
            return "" if value is None else str(value)

        def _fmt_dt(value: datetime | None) -> str:
            return "" if value is None else value.isoformat()

        def _fmt_int(value: int | None) -> str:
            return "" if value is None else str(value)

        return [
            row.trade_id,
            row.symbol,
            row.side,
            _fmt_dt(row.entry_time),
            _fmt_dt(row.exit_time),
            _fmt_decimal(row.units),
            _fmt_decimal(row.entry_price),
            _fmt_decimal(row.exit_price),
            _fmt_decimal(row.fees),
            _fmt_decimal(row.realized_pnl),
            _fmt_int(row.holding_period_seconds),
        ]

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _generate_bundle(
        self,
        export_type: ExportType,
        object_id: str,
        requested_by: str,
        exported_at: datetime,
    ) -> bytes:
        """
        Generate an in-memory zip bundle containing export data.

        Structure:
        - metadata.json: export metadata.
        - README.txt: simple description.
        - data.csv (TRADES) or results.json (RUNS) or none (ARTIFACTS).

        Args:
            export_type: Type of export.
            object_id: ULID of the exported object.
            requested_by: ULID of the requester.
            exported_at: Timestamp of export.

        Returns:
            Raw bytes of the zip file.

        Raises:
            OSError: If zip creation fails.
        """
        bio = io.BytesIO()

        with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
            # Write metadata.json
            metadata = {
                "export_type": export_type.value,
                "object_id": object_id,
                "exported_at": exported_at.isoformat(),
                "requested_by": requested_by,
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

            # Write README.txt
            readme = (
                f"FXLab Export Bundle\n"
                f"==================\n"
                f"\n"
                f"Export Type: {export_type.value}\n"
                f"Object ID: {object_id}\n"
                f"Exported At: {exported_at.isoformat()}\n"
                f"Requested By: {requested_by}\n"
                f"\n"
                f"Contents:\n"
                f"  - metadata.json: Export metadata\n"
            )

            # Write type-specific data file
            if export_type == ExportType.TRADES:
                readme += "  - data.csv: Trade data in CSV format\n"
                zf.writestr("data.csv", self._generate_trades_csv(object_id))
            elif export_type == ExportType.RUNS:
                readme += "  - results.json: Run results in JSON format\n"
                zf.writestr("results.json", self._generate_runs_json(object_id))
            # ARTIFACTS type has no data file, just metadata

            zf.writestr("README.txt", readme)

        return bio.getvalue()

    def _generate_trades_csv(self, object_id: str) -> str:
        """
        Generate CSV data for a TRADES export.

        Returns a simple CSV with headers and placeholder rows.
        In production, this would query the trades repository.

        Args:
            object_id: ULID of the run or candidate.

        Returns:
            CSV string.
        """
        csv_lines = [
            "trade_id,symbol,side,quantity,price,timestamp",
            "01HTRADE0ABCD,BTC/USD,BUY,1.0,45000.00,2026-04-13T12:00:00Z",
            "01HTRADE0EFGH,BTC/USD,SELL,0.5,45100.00,2026-04-13T12:30:00Z",
        ]
        return "\n".join(csv_lines)

    def _generate_runs_json(self, object_id: str) -> str:
        """
        Generate JSON data for a RUNS export.

        Returns a simple JSON object with run metadata and results.
        In production, this would query the run repository.

        Args:
            object_id: ULID of the run.

        Returns:
            JSON string.
        """
        results = {
            "run_id": object_id,
            "status": "complete",
            "start_time": "2026-04-12T00:00:00Z",
            "end_time": "2026-04-13T00:00:00Z",
            "trades": 10,
            "profit_loss": 5250.00,
            "win_rate": 0.65,
        }
        return json.dumps(results, indent=2)
