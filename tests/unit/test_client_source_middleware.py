"""
Tests for ClientSourceMiddleware — extracts X-Client-Source header (BE-07).

Responsibilities:
- Verify middleware extracts X-Client-Source header correctly.
- Verify valid values are accepted (web-desktop, web-mobile, api).
- Verify invalid values default to None.
- Verify missing header defaults to None.
- Verify source is available in request state for downstream handlers.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from starlette.testclient import TestClient

from services.api.middleware.client_source import ClientSourceMiddleware


class TestClientSourceMiddlewareExtractsHeader:
    """Test header extraction and validation."""

    def test_middleware_extracts_valid_web_desktop_header(self):
        """Verify middleware extracts and stores web-desktop source."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.get("/test")
        async def test_handler(request: Request):
            source = request.state.client_source
            return PlainTextResponse(content=f"source={source}")

        client = TestClient(app)
        response = client.get("/test", headers={"X-Client-Source": "web-desktop"})
        assert response.status_code == 200
        assert "source=web-desktop" in response.text

    def test_middleware_extracts_valid_web_mobile_header(self):
        """Verify middleware extracts and stores web-mobile source."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.get("/test")
        async def test_handler(request: Request):
            source = request.state.client_source
            return PlainTextResponse(content=f"source={source}")

        client = TestClient(app)
        response = client.get("/test", headers={"X-Client-Source": "web-mobile"})
        assert response.status_code == 200
        assert "source=web-mobile" in response.text

    def test_middleware_extracts_valid_api_header(self):
        """Verify middleware extracts and stores api source."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.get("/test")
        async def test_handler(request: Request):
            source = request.state.client_source
            return PlainTextResponse(content=f"source={source}")

        client = TestClient(app)
        response = client.get("/test", headers={"X-Client-Source": "api"})
        assert response.status_code == 200
        assert "source=api" in response.text


class TestClientSourceMiddlewareValidation:
    """Test header validation and default behavior."""

    def test_middleware_rejects_invalid_source_defaults_to_none(self):
        """Verify invalid source value defaults to None."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.get("/test")
        async def test_handler(request: Request):
            source = request.state.client_source
            return PlainTextResponse(content=f"source={source}")

        client = TestClient(app)
        response = client.get("/test", headers={"X-Client-Source": "invalid-source"})
        assert response.status_code == 200
        assert "source=None" in response.text

    def test_middleware_defaults_to_none_when_header_missing(self):
        """Verify missing X-Client-Source header defaults to None."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.get("/test")
        async def test_handler(request: Request):
            source = request.state.client_source
            return PlainTextResponse(content=f"source={source}")

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert "source=None" in response.text

    def test_middleware_defaults_to_none_for_empty_header(self):
        """Verify empty X-Client-Source header defaults to None."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.get("/test")
        async def test_handler(request: Request):
            source = request.state.client_source
            return PlainTextResponse(content=f"source={source}")

        client = TestClient(app)
        response = client.get("/test", headers={"X-Client-Source": ""})
        assert response.status_code == 200
        assert "source=None" in response.text

    def test_middleware_case_sensitive_validation(self):
        """Verify validation is case-sensitive (Web-Desktop should be invalid)."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.get("/test")
        async def test_handler(request: Request):
            source = request.state.client_source
            return PlainTextResponse(content=f"source={source}")

        client = TestClient(app)
        response = client.get("/test", headers={"X-Client-Source": "Web-Desktop"})
        assert response.status_code == 200
        assert "source=None" in response.text


class TestClientSourceMiddlewareRequestFlow:
    """Test that middleware doesn't block requests, only extracts source."""

    def test_middleware_allows_request_regardless_of_source(self):
        """Verify middleware does not reject requests based on source."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.post("/api/test")
        async def test_handler(request: Request):
            return PlainTextResponse(content="ok")

        client = TestClient(app)
        # Valid source
        response = client.post("/api/test", headers={"X-Client-Source": "web-desktop"})
        assert response.status_code == 200

        # Invalid source
        response = client.post("/api/test", headers={"X-Client-Source": "invalid"})
        assert response.status_code == 200

        # Missing source
        response = client.post("/api/test")
        assert response.status_code == 200

    def test_middleware_works_with_request_body(self):
        """Verify middleware doesn't interfere with request body parsing."""
        app = FastAPI()
        app.add_middleware(ClientSourceMiddleware)

        @app.post("/api/test")
        async def test_handler(request: Request):
            source = request.state.client_source
            body = await request.json()
            return PlainTextResponse(content=f"source={source},name={body['name']}")

        client = TestClient(app)
        response = client.post(
            "/api/test",
            headers={"X-Client-Source": "api"},
            json={"name": "test"},
        )
        assert response.status_code == 200
        assert "source=api,name=test" in response.text
