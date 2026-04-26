"""
Unit tests for /datasets admin route handlers (M4.E3).

Covers:
- GET  /datasets/                — paginated list, filters compose
- POST /datasets/                — register a new dataset (returns 201)
- PATCH /datasets/{ref}          — toggle certification, update version
- 422 paths: empty body, invalid pagination
- 404 path: PATCH against unknown dataset_ref
- 401 path: missing auth header
- POST /datasets/ persists and GET /datasets/ returns the new row

The router is wired against an in-memory MockDatasetRepository wrapped
in the real :class:`DatasetService` so the tests exercise the full
service+route slice without a database.

Example:
    pytest tests/unit/test_datasets_routes.py -v
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_dataset_repository import MockDatasetRepository
from services.api.auth import ROLE_SCOPES, AuthenticatedUser, get_current_user
from services.api.main import app
from services.api.routes.datasets import set_dataset_service
from services.api.services.dataset_service import DatasetService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_ADMIN_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    role="admin",
    email="admin@fxlab.test",
    scopes=ROLE_SCOPES["admin"],
)


@pytest.fixture()
def admin_client() -> Iterator[tuple[TestClient, MockDatasetRepository]]:
    """
    Wire the /datasets router with a real DatasetService backed by an
    in-memory mock repository, then yield a TestClient + the mock repo.

    The mock repo lets each test inspect persistence side-effects
    (count, find_by_ref) directly without the SQL stack.
    """
    repo = MockDatasetRepository()
    service = DatasetService(repo=repo)
    set_dataset_service(service)

    async def _fake_get_current_user() -> AuthenticatedUser:
        return _ADMIN_USER

    app.dependency_overrides[get_current_user] = _fake_get_current_user

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, repo
    finally:
        app.dependency_overrides.clear()
        set_dataset_service(None)
        repo.clear()


def _admin_headers() -> dict[str, str]:
    """Authorization headers using the TEST_TOKEN."""
    return {"Authorization": "Bearer TEST_TOKEN"}


# ---------------------------------------------------------------------------
# GET /datasets/ — list
# ---------------------------------------------------------------------------


class TestListDatasets:
    def test_empty_catalog_returns_empty_envelope(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        resp = client.get("/datasets/", headers=_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["datasets"] == []
        assert body["total_count"] == 0
        assert body["total_pages"] == 0
        assert body["page"] == 1
        assert body["page_size"] == 20

    def test_returns_registered_rows(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        # Register two datasets via the POST endpoint so we exercise
        # the full slice.
        client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "fx-eurusd-15m",
                "symbols": ["EURUSD"],
                "timeframe": "15m",
                "source": "oanda",
                "version": "v1",
            },
        )
        client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "fx-gbpusd-1h",
                "symbols": ["GBPUSD"],
                "timeframe": "1h",
                "source": "alpaca",
                "version": "v1",
                "is_certified": True,
            },
        )

        resp = client.get("/datasets/", headers=_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 2
        refs = [d["dataset_ref"] for d in body["datasets"]]
        assert refs == ["fx-eurusd-15m", "fx-gbpusd-1h"]
        # is_certified is honoured on the second row.
        cert_map = {d["dataset_ref"]: d["is_certified"] for d in body["datasets"]}
        assert cert_map["fx-gbpusd-1h"] is True
        assert cert_map["fx-eurusd-15m"] is False

    def test_filter_by_source(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        for ref, source in [("a-ref", "oanda"), ("b-ref", "alpaca")]:
            client.post(
                "/datasets/",
                headers=_admin_headers(),
                json={
                    "dataset_ref": ref,
                    "symbols": ["X"],
                    "timeframe": "1d",
                    "source": source,
                    "version": "v1",
                },
            )
        resp = client.get(
            "/datasets/",
            headers=_admin_headers(),
            params={"source": "oanda"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        assert body["datasets"][0]["dataset_ref"] == "a-ref"

    def test_filter_by_is_certified(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "cert-ref",
                "symbols": ["X"],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
                "is_certified": True,
            },
        )
        client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "uncert-ref",
                "symbols": ["X"],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
            },
        )
        resp = client.get(
            "/datasets/",
            headers=_admin_headers(),
            params={"is_certified": "true"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        assert body["datasets"][0]["dataset_ref"] == "cert-ref"

    def test_filter_by_q_substring(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        for ref in ["fx-eurusd-15m", "fx-gbpusd-1h"]:
            client.post(
                "/datasets/",
                headers=_admin_headers(),
                json={
                    "dataset_ref": ref,
                    "symbols": ["X"],
                    "timeframe": "1d",
                    "source": "x",
                    "version": "v1",
                },
            )
        resp = client.get(
            "/datasets/",
            headers=_admin_headers(),
            params={"q": "EUR"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        assert body["datasets"][0]["dataset_ref"] == "fx-eurusd-15m"

    def test_pagination(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        for n in range(5):
            client.post(
                "/datasets/",
                headers=_admin_headers(),
                json={
                    "dataset_ref": f"ref-{n}",
                    "symbols": ["X"],
                    "timeframe": "1d",
                    "source": "x",
                    "version": "v1",
                },
            )
        resp = client.get(
            "/datasets/",
            headers=_admin_headers(),
            params={"page": 2, "page_size": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 2
        assert body["page_size"] == 2
        assert body["total_count"] == 5
        assert body["total_pages"] == 3
        assert [d["dataset_ref"] for d in body["datasets"]] == ["ref-2", "ref-3"]

    def test_invalid_page_returns_422(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        resp = client.get(
            "/datasets/",
            headers=_admin_headers(),
            params={"page": 0},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /datasets/ — register
# ---------------------------------------------------------------------------


class TestRegisterDataset:
    def test_persists_and_returns_201(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, repo = admin_client
        resp = client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "fx-eurusd-15m",
                "symbols": ["EURUSD"],
                "timeframe": "15m",
                "source": "oanda",
                "version": "v1",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["dataset_ref"] == "fx-eurusd-15m"
        assert body["symbols"] == ["EURUSD"]
        assert body["is_certified"] is False
        # Persistence side-effect: the row landed in the repo.
        assert repo.count() == 1
        record = repo.find_by_ref("fx-eurusd-15m")
        assert record is not None
        assert record.symbols == ["EURUSD"]

    def test_persisted_row_appears_in_get(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        # The "POST persists; GET returns" gate from the prompt.
        client, _ = admin_client
        post_resp = client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "fx-test-roundtrip",
                "symbols": ["EURUSD"],
                "timeframe": "1h",
                "source": "synthetic",
                "version": "v9",
            },
        )
        assert post_resp.status_code == 201

        get_resp = client.get("/datasets/", headers=_admin_headers())
        assert get_resp.status_code == 200
        refs = [d["dataset_ref"] for d in get_resp.json()["datasets"]]
        assert "fx-test-roundtrip" in refs

    def test_with_is_certified_true_flips_flag(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, repo = admin_client
        resp = client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "cert-on-create",
                "symbols": ["X"],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
                "is_certified": True,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["is_certified"] is True
        record = repo.find_by_ref("cert-on-create")
        assert record is not None
        assert record.is_certified is True

    def test_empty_symbols_returns_422(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        resp = client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "x",
                "symbols": [],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
            },
        )
        assert resp.status_code == 422

    def test_missing_dataset_ref_returns_422(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        resp = client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "symbols": ["X"],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
            },
        )
        assert resp.status_code == 422

    def test_missing_auth_returns_401(self) -> None:
        # Fresh client without dependency overrides — exercises the
        # require_scope guard from the auth layer.
        client = TestClient(app)
        resp = client.post(
            "/datasets/",
            json={
                "dataset_ref": "x",
                "symbols": ["X"],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
            },
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /datasets/{dataset_ref} — update
# ---------------------------------------------------------------------------


class TestUpdateDataset:
    def test_toggles_certification(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, repo = admin_client
        client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "to-cert",
                "symbols": ["X"],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
            },
        )
        resp = client.patch(
            "/datasets/to-cert",
            headers=_admin_headers(),
            json={"is_certified": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_certified"] is True
        record = repo.find_by_ref("to-cert")
        assert record is not None
        assert record.is_certified is True

    def test_updates_version(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, repo = admin_client
        client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "to-vbump",
                "symbols": ["X"],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
            },
        )
        resp = client.patch(
            "/datasets/to-vbump",
            headers=_admin_headers(),
            json={"version": "v9"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == "v9"
        record = repo.find_by_ref("to-vbump")
        assert record is not None
        assert record.version == "v9"

    def test_unknown_ref_returns_404(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        resp = client.patch(
            "/datasets/never-registered",
            headers=_admin_headers(),
            json={"is_certified": True},
        )
        assert resp.status_code == 404

    def test_empty_body_returns_422(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        client.post(
            "/datasets/",
            headers=_admin_headers(),
            json={
                "dataset_ref": "exists",
                "symbols": ["X"],
                "timeframe": "1d",
                "source": "x",
                "version": "v1",
            },
        )
        resp = client.patch(
            "/datasets/exists",
            headers=_admin_headers(),
            json={},
        )
        assert resp.status_code == 422

    def test_extra_field_returns_422(
        self,
        admin_client: tuple[TestClient, MockDatasetRepository],
    ) -> None:
        client, _ = admin_client
        resp = client.patch(
            "/datasets/anything",
            headers=_admin_headers(),
            json={"is_certified": True, "rogue_field": "x"},
        )
        assert resp.status_code == 422
