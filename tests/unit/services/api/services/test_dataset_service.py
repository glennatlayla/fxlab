"""
Unit tests for services.api.services.dataset_service.DatasetService (M4.E3).

Scope:
    Verify the catalog service layer against an in-memory mock
    repository:
        - lookup happy path → ResolvedDataset
        - lookup miss → DatasetNotFoundError
        - lookup empty / blank ref → DatasetNotFoundError
        - register_dataset INSERT path
        - register_dataset UPDATE path (preserves id + is_certified)
        - register_dataset rejects empty / blank arguments
        - list_known_refs proxies to repo
        - is_certified happy path + miss + uncertified
"""

from __future__ import annotations

import pytest

from libs.contracts.interfaces.dataset_repository_interface import (
    DatasetRecord,
)
from libs.contracts.mocks.mock_dataset_repository import MockDatasetRepository
from libs.strategy_ir.interfaces.dataset_service_interface import (
    DatasetNotFoundError,
    ResolvedDataset,
)
from services.api.services.dataset_service import DatasetService


@pytest.fixture()
def repo() -> MockDatasetRepository:
    return MockDatasetRepository()


@pytest.fixture()
def service(repo: MockDatasetRepository) -> DatasetService:
    return DatasetService(repo=repo)


def _seed(
    repo: MockDatasetRepository,
    *,
    dataset_ref: str = "fx-eurusd-15m-certified-v3",
    symbols: list[str] | None = None,
    is_certified: bool = False,
) -> DatasetRecord:
    record = DatasetRecord(
        id="01HSEED0000000000000000001",
        dataset_ref=dataset_ref,
        symbols=list(symbols) if symbols is not None else ["EURUSD"],
        timeframe="15m",
        source="synthetic",
        version="v3",
        is_certified=is_certified,
    )
    return repo.save(record)


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


class TestLookup:
    def test_returns_resolved_dataset_on_hit(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo)
        result = service.lookup("fx-eurusd-15m-certified-v3")
        assert isinstance(result, ResolvedDataset)
        assert result.dataset_ref == "fx-eurusd-15m-certified-v3"
        assert result.symbols == ["EURUSD"]
        assert result.dataset_id == "01HSEED0000000000000000001"

    def test_miss_raises_not_found(self, service: DatasetService) -> None:
        with pytest.raises(DatasetNotFoundError) as excinfo:
            service.lookup("does-not-exist")
        assert excinfo.value.dataset_ref == "does-not-exist"

    def test_empty_ref_raises_not_found(self, service: DatasetService) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.lookup("")

    def test_returns_full_symbol_list(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(
            repo,
            dataset_ref="fx-majors-h1-certified-v1",
            symbols=["EURUSD", "GBPUSD", "USDJPY"],
        )
        result = service.lookup("fx-majors-h1-certified-v1")
        assert result.symbols == ["EURUSD", "GBPUSD", "USDJPY"]


# ---------------------------------------------------------------------------
# register_dataset
# ---------------------------------------------------------------------------


class TestRegisterDataset:
    def test_inserts_new_entry(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        service.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v3",
        )
        record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
        assert record is not None
        assert record.symbols == ["EURUSD"]
        assert record.timeframe == "15m"
        assert record.source == "oanda"
        assert record.version == "v3"
        # Service-generated ULID must be a 26-char string.
        assert len(record.id) == 26
        # Defaults to NOT certified on first insert.
        assert record.is_certified is False

    def test_updates_existing_entry_in_place(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        seeded = _seed(repo)
        service.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD", "GBPUSD"],
            timeframe="15m",
            source="oanda",
            version="v4",
        )
        record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
        assert record is not None
        assert record.symbols == ["EURUSD", "GBPUSD"]
        assert record.version == "v4"
        # ID must be preserved across the upsert.
        assert record.id == seeded.id

    def test_update_preserves_certification(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo, is_certified=True)
        service.register_dataset(
            "fx-eurusd-15m-certified-v3",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v4",
        )
        record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
        assert record is not None
        assert record.is_certified is True

    @pytest.mark.parametrize(
        "field, value",
        [
            ("dataset_ref", ""),
            ("symbols", []),
            ("timeframe", ""),
            ("source", ""),
            ("version", ""),
        ],
    )
    def test_rejects_empty_arguments(
        self,
        service: DatasetService,
        field: str,
        value: object,
    ) -> None:
        kwargs: dict[str, object] = {
            "dataset_ref": "fx-eurusd-15m-certified-v3",
            "symbols": ["EURUSD"],
            "timeframe": "15m",
            "source": "oanda",
            "version": "v3",
        }
        kwargs[field] = value
        with pytest.raises(ValueError):
            service.register_dataset(
                kwargs["dataset_ref"],  # type: ignore[arg-type]
                symbols=kwargs["symbols"],  # type: ignore[arg-type]
                timeframe=kwargs["timeframe"],  # type: ignore[arg-type]
                source=kwargs["source"],  # type: ignore[arg-type]
                version=kwargs["version"],  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# list_known_refs
# ---------------------------------------------------------------------------


class TestListKnownRefs:
    def test_returns_sorted_refs(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo, dataset_ref="z-ref")
        _seed(repo, dataset_ref="a-ref")
        _seed(repo, dataset_ref="m-ref")
        # MockDatasetRepository.save reuses the seeded record id, so
        # _seed three times overwrites — re-save with distinct ids.
        # Easier: use service.register_dataset which generates ULIDs.
        repo.clear()
        service.register_dataset(
            "z-ref",
            symbols=["X"],
            timeframe="1d",
            source="synthetic",
            version="v1",
        )
        service.register_dataset(
            "a-ref",
            symbols=["X"],
            timeframe="1d",
            source="synthetic",
            version="v1",
        )
        service.register_dataset(
            "m-ref",
            symbols=["X"],
            timeframe="1d",
            source="synthetic",
            version="v1",
        )
        assert service.list_known_refs() == ["a-ref", "m-ref", "z-ref"]

    def test_empty_catalog_returns_empty_list(
        self,
        service: DatasetService,
    ) -> None:
        assert service.list_known_refs() == []


# ---------------------------------------------------------------------------
# is_certified
# ---------------------------------------------------------------------------


class TestIsCertified:
    def test_returns_true_when_certified(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo, is_certified=True)
        assert service.is_certified("fx-eurusd-15m-certified-v3") is True

    def test_returns_false_when_not_certified(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo, is_certified=False)
        assert service.is_certified("fx-eurusd-15m-certified-v3") is False

    def test_returns_false_when_unknown(self, service: DatasetService) -> None:
        assert service.is_certified("never-registered") is False

    def test_returns_false_for_empty_ref(self, service: DatasetService) -> None:
        assert service.is_certified("") is False


# ---------------------------------------------------------------------------
# list_paged
# ---------------------------------------------------------------------------


class TestListPaged:
    def test_empty_catalog_returns_empty_envelope(
        self,
        service: DatasetService,
    ) -> None:
        page = service.list_paged(page=1, page_size=20)
        assert page.datasets == []
        assert page.total_count == 0
        assert page.total_pages == 0
        assert page.page == 1
        assert page.page_size == 20

    def test_returns_paged_slice_sorted_by_ref(
        self,
        service: DatasetService,
    ) -> None:
        for ref in ["z-ref", "a-ref", "m-ref"]:
            service.register_dataset(
                ref,
                symbols=["X"],
                timeframe="1d",
                source="synthetic",
                version="v1",
            )
        page = service.list_paged(page=1, page_size=20)
        assert [d.dataset_ref for d in page.datasets] == ["a-ref", "m-ref", "z-ref"]
        assert page.total_count == 3
        assert page.total_pages == 1

    def test_filters_by_source(
        self,
        service: DatasetService,
    ) -> None:
        service.register_dataset(
            "a-ref",
            symbols=["X"],
            timeframe="1d",
            source="oanda",
            version="v1",
        )
        service.register_dataset(
            "b-ref",
            symbols=["Y"],
            timeframe="1d",
            source="alpaca",
            version="v1",
        )
        page = service.list_paged(page=1, page_size=20, source_filter="oanda")
        assert [d.dataset_ref for d in page.datasets] == ["a-ref"]
        assert page.total_count == 1

    def test_filters_by_certification(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo, dataset_ref="cert-ref", is_certified=True)
        _seed(repo, dataset_ref="uncert-ref", is_certified=False)
        page = service.list_paged(page=1, page_size=20, is_certified=True)
        assert [d.dataset_ref for d in page.datasets] == ["cert-ref"]

    def test_filters_by_q_substring(
        self,
        service: DatasetService,
    ) -> None:
        service.register_dataset(
            "fx-eurusd-15m",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v1",
        )
        service.register_dataset(
            "fx-gbpusd-1h",
            symbols=["GBPUSD"],
            timeframe="1h",
            source="oanda",
            version="v1",
        )
        page = service.list_paged(page=1, page_size=20, q="EUR")
        assert [d.dataset_ref for d in page.datasets] == ["fx-eurusd-15m"]
        # Empty q returns everything (treated as unset).
        page2 = service.list_paged(page=1, page_size=20, q="")
        assert len(page2.datasets) == 2

    def test_pagination_slices_correctly(
        self,
        service: DatasetService,
    ) -> None:
        for n in range(5):
            service.register_dataset(
                f"ref-{n}",
                symbols=["X"],
                timeframe="1d",
                source="synthetic",
                version="v1",
            )
        page1 = service.list_paged(page=1, page_size=2)
        assert [d.dataset_ref for d in page1.datasets] == ["ref-0", "ref-1"]
        assert page1.total_count == 5
        assert page1.total_pages == 3
        page3 = service.list_paged(page=3, page_size=2)
        assert [d.dataset_ref for d in page3.datasets] == ["ref-4"]


# ---------------------------------------------------------------------------
# update_certification
# ---------------------------------------------------------------------------


class TestUpdateCertification:
    def test_flips_flag_to_true(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo, is_certified=False)
        service.update_certification("fx-eurusd-15m-certified-v3", is_certified=True)
        record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
        assert record is not None
        assert record.is_certified is True

    def test_flips_flag_to_false(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo, is_certified=True)
        service.update_certification("fx-eurusd-15m-certified-v3", is_certified=False)
        record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
        assert record is not None
        assert record.is_certified is False

    def test_unknown_ref_raises_not_found(
        self,
        service: DatasetService,
    ) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.update_certification("never-registered", is_certified=True)

    def test_empty_ref_raises_not_found(
        self,
        service: DatasetService,
    ) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.update_certification("", is_certified=True)


# ---------------------------------------------------------------------------
# update_version
# ---------------------------------------------------------------------------


class TestUpdateVersion:
    def test_updates_version_in_place(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo)
        service.update_version("fx-eurusd-15m-certified-v3", version="v9")
        record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
        assert record is not None
        assert record.version == "v9"

    def test_preserves_other_fields(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        seeded = _seed(repo, is_certified=True)
        service.update_version("fx-eurusd-15m-certified-v3", version="v9")
        record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
        assert record is not None
        assert record.is_certified is True
        assert record.symbols == seeded.symbols
        assert record.timeframe == seeded.timeframe
        assert record.source == seeded.source

    def test_unknown_ref_raises_not_found(
        self,
        service: DatasetService,
    ) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.update_version("never-registered", version="v1")

    def test_empty_version_raises_value_error(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo)
        with pytest.raises(ValueError):
            service.update_version("fx-eurusd-15m-certified-v3", version="")


# ---------------------------------------------------------------------------
# get_record
# ---------------------------------------------------------------------------


class TestGetRecord:
    def test_returns_full_metadata(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo, is_certified=True)
        item = service.get_record("fx-eurusd-15m-certified-v3")
        assert item.dataset_ref == "fx-eurusd-15m-certified-v3"
        assert item.timeframe == "15m"
        assert item.source == "synthetic"
        assert item.version == "v3"
        assert item.is_certified is True
        assert item.symbols == ["EURUSD"]

    def test_unknown_ref_raises_not_found(
        self,
        service: DatasetService,
    ) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.get_record("never-registered")

    def test_empty_ref_raises_not_found(
        self,
        service: DatasetService,
    ) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.get_record("")


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


class TestCount:
    def test_empty_catalog_returns_zero(self, service: DatasetService) -> None:
        assert service.count() == 0

    def test_returns_repository_count(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        _seed(repo)
        _seed(
            repo,
            dataset_ref="fx-gbpusd-15m-v1",
            symbols=["GBPUSD"],
        )
        assert service.count() == 2

    def test_delegates_to_repository(
        self,
        service: DatasetService,
        repo: MockDatasetRepository,
    ) -> None:
        """count() must round-trip via the repository, not cache its own state."""
        assert service.count() == 0
        _seed(repo)
        # The service must re-query — never cache.
        assert service.count() == 1
        repo.clear()
        assert service.count() == 0
