"""
M0 Bootstrap: Project Structure Tests

These tests verify that the Phase 2 directory structure and Python packages
are correctly established and importable.

All tests must FAIL before implementation exists.
"""
import importlib
import sys
from pathlib import Path

import pytest


class TestAC1_DirectoryStructure:
    """AC1: Phase 2 directory structure must exist according to target shape."""

    def test_ac1_services_directory_exists(self):
        """Verify services/ directory exists."""
        services_dir = Path("services")
        assert services_dir.exists(), "services/ directory must exist"
        assert services_dir.is_dir(), "services/ must be a directory"

    def test_ac1_api_service_structure_exists(self):
        """Verify services/api/ structure exists."""
        api_dir = Path("services/api")
        assert api_dir.exists(), "services/api/ directory must exist"
        
        routes_dir = api_dir / "routes"
        assert routes_dir.exists(), "services/api/routes/ directory must exist"

    def test_ac1_strategy_compiler_service_exists(self):
        """Verify services/strategy_compiler/ exists."""
        compiler_dir = Path("services/strategy_compiler")
        assert compiler_dir.exists(), "services/strategy_compiler/ directory must exist"

    def test_ac1_research_worker_service_exists(self):
        """Verify services/research_worker/ exists."""
        worker_dir = Path("services/research_worker")
        assert worker_dir.exists(), "services/research_worker/ directory must exist"

    def test_ac1_optimization_worker_service_exists(self):
        """Verify services/optimization_worker/ exists."""
        opt_dir = Path("services/optimization_worker")
        assert opt_dir.exists(), "services/optimization_worker/ directory must exist"

    def test_ac1_readiness_service_exists(self):
        """Verify services/readiness_service/ exists."""
        readiness_dir = Path("services/readiness_service")
        assert readiness_dir.exists(), "services/readiness_service/ directory must exist"

    def test_ac1_libs_strategy_compiler_exists(self):
        """Verify libs/strategy_compiler/ exists."""
        lib_dir = Path("libs/strategy_compiler")
        assert lib_dir.exists(), "libs/strategy_compiler/ directory must exist"

    def test_ac1_libs_strategy_ir_exists(self):
        """Verify libs/strategy_ir/ exists."""
        ir_dir = Path("libs/strategy_ir")
        assert ir_dir.exists(), "libs/strategy_ir/ directory must exist"

    def test_ac1_libs_experiment_plan_exists(self):
        """Verify libs/experiment_plan/ exists."""
        exp_dir = Path("libs/experiment_plan")
        assert exp_dir.exists(), "libs/experiment_plan/ directory must exist"

    def test_ac1_libs_risk_exists(self):
        """Verify libs/risk/ exists."""
        risk_dir = Path("libs/risk")
        assert risk_dir.exists(), "libs/risk/ directory must exist"


class TestAC2_PythonPackageStructure:
    """AC2: All Phase 2 directories must be valid Python packages."""

    def test_ac2_services_api_is_package(self):
        """Verify services/api/ is a Python package."""
        init_file = Path("services/api/__init__.py")
        assert init_file.exists(), "services/api/__init__.py must exist"

    def test_ac2_services_api_routes_is_package(self):
        """Verify services/api/routes/ is a Python package."""
        init_file = Path("services/api/routes/__init__.py")
        assert init_file.exists(), "services/api/routes/__init__.py must exist"

    def test_ac2_strategy_compiler_service_is_package(self):
        """Verify services/strategy_compiler/ is a Python package."""
        init_file = Path("services/strategy_compiler/__init__.py")
        assert init_file.exists(), "services/strategy_compiler/__init__.py must exist"

    def test_ac2_research_worker_is_package(self):
        """Verify services/research_worker/ is a Python package."""
        init_file = Path("services/research_worker/__init__.py")
        assert init_file.exists(), "services/research_worker/__init__.py must exist"

    def test_ac2_optimization_worker_is_package(self):
        """Verify services/optimization_worker/ is a Python package."""
        init_file = Path("services/optimization_worker/__init__.py")
        assert init_file.exists(), "services/optimization_worker/__init__.py must exist"

    def test_ac2_readiness_service_is_package(self):
        """Verify services/readiness_service/ is a Python package."""
        init_file = Path("services/readiness_service/__init__.py")
        assert init_file.exists(), "services/readiness_service/__init__.py must exist"

    def test_ac2_libs_strategy_compiler_is_package(self):
        """Verify libs/strategy_compiler/ is a Python package."""
        init_file = Path("libs/strategy_compiler/__init__.py")
        assert init_file.exists(), "libs/strategy_compiler/__init__.py must exist"

    def test_ac2_libs_strategy_ir_is_package(self):
        """Verify libs/strategy_ir/ is a Python package."""
        init_file = Path("libs/strategy_ir/__init__.py")
        assert init_file.exists(), "libs/strategy_ir/__init__.py must exist"

    def test_ac2_libs_experiment_plan_is_package(self):
        """Verify libs/experiment_plan/ is a Python package."""
        init_file = Path("libs/experiment_plan/__init__.py")
        assert init_file.exists(), "libs/experiment_plan/__init__.py must exist"

    def test_ac2_libs_risk_is_package(self):
        """Verify libs/risk/ is a Python package."""
        init_file = Path("libs/risk/__init__.py")
        assert init_file.exists(), "libs/risk/__init__.py must exist"


class TestAC3_ServiceEntryPoints:
    """AC3: Service entry points must exist with correct naming."""

    def test_ac3_api_main_exists(self):
        """Verify services/api/main.py exists (not app.py)."""
        main_file = Path("services/api/main.py")
        assert main_file.exists(), "services/api/main.py must exist (never app.py)"

    def test_ac3_strategy_compiler_main_exists(self):
        """Verify services/strategy_compiler/main.py exists."""
        main_file = Path("services/strategy_compiler/main.py")
        assert main_file.exists(), "services/strategy_compiler/main.py must exist"

    def test_ac3_research_worker_main_exists(self):
        """Verify services/research_worker/main.py exists."""
        main_file = Path("services/research_worker/main.py")
        assert main_file.exists(), "services/research_worker/main.py must exist"

    def test_ac3_optimization_worker_main_exists(self):
        """Verify services/optimization_worker/main.py exists."""
        main_file = Path("services/optimization_worker/main.py")
        assert main_file.exists(), "services/optimization_worker/main.py must exist"

    def test_ac3_readiness_service_main_exists(self):
        """Verify services/readiness_service/main.py exists."""
        main_file = Path("services/readiness_service/main.py")
        assert main_file.exists(), "services/readiness_service/main.py must exist"


class TestAC4_RouteFiles:
    """AC4: API route files must exist in correct location."""

    def test_ac4_strategies_route_exists(self):
        """Verify services/api/routes/strategies.py exists."""
        route_file = Path("services/api/routes/strategies.py")
        assert route_file.exists(), "services/api/routes/strategies.py must exist"

    def test_ac4_runs_route_exists(self):
        """Verify services/api/routes/runs.py exists."""
        route_file = Path("services/api/routes/runs.py")
        assert route_file.exists(), "services/api/routes/runs.py must exist"

    def test_ac4_readiness_route_exists(self):
        """Verify services/api/routes/readiness.py exists."""
        route_file = Path("services/api/routes/readiness.py")
        assert route_file.exists(), "services/api/routes/readiness.py must exist"

    def test_ac4_exports_route_exists(self):
        """Verify services/api/routes/exports.py exists."""
        route_file = Path("services/api/routes/exports.py")
        assert route_file.exists(), "services/api/routes/exports.py must exist"


class TestAC5_PackageImportability:
    """AC5: All Phase 2 packages must be importable without errors."""

    def test_ac5_services_api_importable(self):
        """Verify services.api package can be imported."""
        # Must fail if package doesn't exist or has import errors
        try:
            import services.api
            assert services.api is not None
        except ImportError as e:
            pytest.fail(f"services.api must be importable: {e}")

    def test_ac5_services_api_routes_importable(self):
        """Verify services.api.routes package can be imported."""
        try:
            import services.api.routes
            assert services.api.routes is not None
        except ImportError as e:
            pytest.fail(f"services.api.routes must be importable: {e}")

    def test_ac5_libs_strategy_compiler_importable(self):
        """Verify libs.strategy_compiler package can be imported."""
        try:
            import libs.strategy_compiler
            assert libs.strategy_compiler is not None
        except ImportError as e:
            pytest.fail(f"libs.strategy_compiler must be importable: {e}")

    def test_ac5_libs_strategy_ir_importable(self):
        """Verify libs.strategy_ir package can be imported."""
        try:
            import libs.strategy_ir
            assert libs.strategy_ir is not None
        except ImportError as e:
            pytest.fail(f"libs.strategy_ir must be importable: {e}")

    def test_ac5_libs_experiment_plan_importable(self):
        """Verify libs.experiment_plan package can be imported."""
        try:
            import libs.experiment_plan
            assert libs.experiment_plan is not None
        except ImportError as e:
            pytest.fail(f"libs.experiment_plan must be importable: {e}")

    def test_ac5_libs_risk_importable(self):
        """Verify libs.risk package can be imported."""
        try:
            import libs.risk
            assert libs.risk is not None
        except ImportError as e:
            pytest.fail(f"libs.risk must be importable: {e}")

    def test_ac5_services_strategy_compiler_importable(self):
        """Verify services.strategy_compiler package can be imported."""
        try:
            import services.strategy_compiler
            assert services.strategy_compiler is not None
        except ImportError as e:
            pytest.fail(f"services.strategy_compiler must be importable: {e}")

    def test_ac5_services_research_worker_importable(self):
        """Verify services.research_worker package can be imported."""
        try:
            import services.research_worker
            assert services.research_worker is not None
        except ImportError as e:
            pytest.fail(f"services.research_worker must be importable: {e}")

    def test_ac5_services_optimization_worker_importable(self):
        """Verify services.optimization_worker package can be imported."""
        try:
            import services.optimization_worker
            assert services.optimization_worker is not None
        except ImportError as e:
            pytest.fail(f"services.optimization_worker must be importable: {e}")

    def test_ac5_services_readiness_service_importable(self):
        """Verify services.readiness_service package can be imported."""
        try:
            import services.readiness_service
            assert services.readiness_service is not None
        except ImportError as e:
            pytest.fail(f"services.readiness_service must be importable: {e}")


class TestAC6_InterfaceDirectories:
    """AC6: Interface directories must exist for service abstractions."""

    def test_ac6_strategy_compiler_interfaces_exists(self):
        """Verify libs/strategy_compiler/interfaces/ exists."""
        interfaces_dir = Path("libs/strategy_compiler/interfaces")
        assert interfaces_dir.exists(), "libs/strategy_compiler/interfaces/ must exist"
        
        init_file = interfaces_dir / "__init__.py"
        assert init_file.exists(), "libs/strategy_compiler/interfaces/__init__.py must exist"

    def test_ac6_strategy_ir_interfaces_exists(self):
        """Verify libs/strategy_ir/interfaces/ exists."""
        interfaces_dir = Path("libs/strategy_ir/interfaces")
        assert interfaces_dir.exists(), "libs/strategy_ir/interfaces/ must exist"
        
        init_file = interfaces_dir / "__init__.py"
        assert init_file.exists(), "libs/strategy_ir/interfaces/__init__.py must exist"

    def test_ac6_experiment_plan_interfaces_exists(self):
        """Verify libs/experiment_plan/interfaces/ exists."""
        interfaces_dir = Path("libs/experiment_plan/interfaces")
        assert interfaces_dir.exists(), "libs/experiment_plan/interfaces/ must exist"
        
        init_file = interfaces_dir / "__init__.py"
        assert init_file.exists(), "libs/experiment_plan/interfaces/__init__.py must exist"

    def test_ac6_risk_interfaces_exists(self):
        """Verify libs/risk/interfaces/ exists."""
        interfaces_dir = Path("libs/risk/interfaces")
        assert interfaces_dir.exists(), "libs/risk/interfaces/ must exist"
        
        init_file = interfaces_dir / "__init__.py"
        assert init_file.exists(), "libs/risk/interfaces/__init__.py must exist"


class TestAC7_TestStructure:
    """AC7: Test directory structure must be established."""

    def test_ac7_unit_tests_directory_exists(self):
        """Verify tests/unit/ directory exists."""
        unit_dir = Path("tests/unit")
        assert unit_dir.exists(), "tests/unit/ directory must exist"

    def test_ac7_integration_tests_directory_exists(self):
        """Verify tests/integration/ directory exists."""
        integration_dir = Path("tests/integration")
        assert integration_dir.exists(), "tests/integration/ directory must exist"

    def test_ac7_root_conftest_exists(self):
        """Verify tests/conftest.py exists (root fixtures)."""
        conftest = Path("tests/conftest.py")
        assert conftest.exists(), "tests/conftest.py must exist"

    def test_ac7_unit_conftest_exists(self):
        """Verify tests/unit/conftest.py exists."""
        conftest = Path("tests/unit/conftest.py")
        assert conftest.exists(), "tests/unit/conftest.py must exist"

    def test_ac7_integration_conftest_exists(self):
        """Verify tests/integration/conftest.py exists."""
        conftest = Path("tests/integration/conftest.py")
        assert conftest.exists(), "tests/integration/conftest.py must exist"


class TestAC8_NoPhase1Violations:
    """AC8: Phase 2 structure must not violate Phase 1 naming conventions."""

    def test_ac8_api_not_named_app_py(self):
        """Verify API entry point is main.py, never app.py."""
        app_file = Path("services/api/app.py")
        assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"

    def test_ac8_libs_contracts_not_modified(self):
        """Verify libs/contracts/ structure is not destroyed."""
        # This assumes Phase 1 exists; if not, this test validates the constraint
        contracts_dir = Path("libs/contracts")
        if contracts_dir.exists():
            # If Phase 1 exists, errors.py should still be there
            errors_file = contracts_dir / "errors.py"
            assert errors_file.exists(), "libs/contracts/errors.py must not be removed"

    def test_ac8_no_duplicate_conftest_in_services(self):
        """Verify no duplicate conftest.py files in service directories."""
        duplicate_locations = [
            Path("services/api/conftest.py"),
            Path("services/strategy_compiler/conftest.py"),
            Path("services/research_worker/conftest.py"),
            Path("services/optimization_worker/conftest.py"),
            Path("services/readiness_service/conftest.py"),
        ]
        
        for location in duplicate_locations:
            assert not location.exists(), (
                f"{location} must NOT exist - use tests/conftest.py, "
                "tests/unit/conftest.py, or tests/integration/conftest.py only"
            )


class TestAC9_DependencyConfiguration:
    """AC9: Phase 2 dependency configuration must exist."""

    def test_ac9_pyproject_toml_exists(self):
        """Verify pyproject.toml exists for Phase 2 dependencies."""
        pyproject = Path("pyproject.toml")
        assert pyproject.exists(), "pyproject.toml must exist"

    def test_ac9_pyproject_contains_phase2_deps(self):
        """Verify pyproject.toml contains Phase 2 specific dependencies."""
        pyproject = Path("pyproject.toml")
        assert pyproject.exists(), "pyproject.toml must exist"
        
        content = pyproject.read_text()
        
        # Phase 2 requires these based on workplan
        required_deps = [
            "optuna",  # optimization sampler
            "numpy",   # numerical operations
            "polars",  # bar-level computation
            "pyarrow", # parquet I/O
        ]
        
        for dep in required_deps:
            assert dep in content.lower(), (
                f"pyproject.toml must include {dep} for Phase 2"
            )


class TestAC10_QualityGateInfrastructure:
    """AC10: Quality gate infrastructure must be runnable."""

    def test_ac10_pytest_ini_exists(self):
        """Verify pytest.ini or pyproject.toml pytest config exists."""
        pytest_ini = Path("pytest.ini")
        pyproject = Path("pyproject.toml")
        
        has_config = pytest_ini.exists() or pyproject.exists()
        assert has_config, "pytest.ini or pyproject.toml must exist for test configuration"

    def test_ac10_ruff_config_exists(self):
        """Verify ruff configuration exists (format/lint)."""
        pyproject = Path("pyproject.toml")
        ruff_toml = Path("ruff.toml")
        
        has_config = pyproject.exists() or ruff_toml.exists()
        assert has_config, "ruff configuration must exist in pyproject.toml or ruff.toml"

    def test_ac10_mypy_config_exists(self):
        """Verify mypy configuration exists (type checking)."""
        pyproject = Path("pyproject.toml")
        mypy_ini = Path("mypy.ini")
        
        has_config = pyproject.exists() or mypy_ini.exists()
        assert has_config, "mypy configuration must exist in pyproject.toml or mypy.ini"
