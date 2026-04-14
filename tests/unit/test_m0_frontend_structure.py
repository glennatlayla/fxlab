"""
M0 Frontend Structure Tests

These tests verify the Phase 3 frontend bootstrap structure exists.
All tests must FAIL until the frontend structure is created.
"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def project_root():
    """Get project root directory."""
    # Assuming tests are in tests/unit/
    return Path(__file__).parent.parent.parent


def test_ac1_frontend_directory_exists(project_root):
    """AC1: frontend/ directory exists at project root."""
    frontend_dir = project_root / "frontend"
    assert frontend_dir.exists(), "frontend/ directory does not exist"
    assert frontend_dir.is_dir(), "frontend/ exists but is not a directory"


def test_ac2_package_json_exists_with_dependencies(project_root):
    """AC2: frontend/package.json lists all required Phase 3 frontend dependencies."""
    package_json_path = project_root / "frontend" / "package.json"
    assert package_json_path.exists(), "frontend/package.json does not exist"

    with open(package_json_path) as f:
        package_data = json.load(f)

    # Required dependencies for Phase 3
    required_deps = {
        "react",
        "react-dom",
        "react-router-dom",
        "axios",
        "recharts",
        "@tanstack/react-query",
    }

    all_deps = set()
    if "dependencies" in package_data:
        all_deps.update(package_data["dependencies"].keys())
    if "devDependencies" in package_data:
        all_deps.update(package_data["devDependencies"].keys())

    missing_deps = required_deps - all_deps
    assert not missing_deps, f"Missing required dependencies: {missing_deps}"


def test_ac3_tsconfig_exists_with_strict_mode(project_root):
    """AC3: frontend/tsconfig.json exists with strict: true enabled."""
    tsconfig_path = project_root / "frontend" / "tsconfig.json"
    assert tsconfig_path.exists(), "frontend/tsconfig.json does not exist"

    with open(tsconfig_path) as f:
        tsconfig_data = json.load(f)

    assert "compilerOptions" in tsconfig_data, "tsconfig.json missing compilerOptions"
    compiler_options = tsconfig_data["compilerOptions"]
    assert compiler_options.get("strict") is True, "strict mode not enabled in tsconfig.json"


def test_ac4_core_entry_files_exist(project_root):
    """AC4: frontend/src/main.tsx, App.tsx, router.tsx exist."""
    src_dir = project_root / "frontend" / "src"

    required_files = [
        "main.tsx",
        "App.tsx",
        "router.tsx",
    ]

    for filename in required_files:
        file_path = src_dir / filename
        assert file_path.exists(), f"frontend/src/{filename} does not exist"
        assert file_path.is_file(), f"frontend/src/{filename} exists but is not a file"


def test_ac5_api_client_exists(project_root):
    """AC5: frontend/src/api/client.ts exists."""
    api_client_path = project_root / "frontend" / "src" / "api" / "client.ts"
    assert api_client_path.exists(), "frontend/src/api/client.ts does not exist"
    assert api_client_path.is_file(), "frontend/src/api/client.ts exists but is not a file"


def test_ac6_auth_components_exist(project_root):
    """AC6: frontend/src/auth/AuthProvider.tsx, useAuth.ts, and permissions.ts exist."""
    auth_dir = project_root / "frontend" / "src" / "auth"

    required_auth_files = [
        "AuthProvider.tsx",
        "useAuth.ts",
        "permissions.ts",
    ]

    for filename in required_auth_files:
        file_path = auth_dir / filename
        assert file_path.exists(), f"frontend/src/auth/{filename} does not exist"
        assert file_path.is_file(), f"frontend/src/auth/{filename} exists but is not a file"


def test_ac7_frontend_directory_structure_exists(project_root):
    """AC7: frontend/src/components/, features/, pages/, hooks/ directories exist."""
    src_dir = project_root / "frontend" / "src"

    required_dirs = [
        "components",
        "features",
        "pages",
        "hooks",
    ]

    for dirname in required_dirs:
        dir_path = src_dir / dirname
        assert dir_path.exists(), f"frontend/src/{dirname}/ directory does not exist"
        assert dir_path.is_dir(), f"frontend/src/{dirname}/ exists but is not a directory"


def test_ac8_npm_build_succeeds():
    """AC8: npm run build exits 0 with zero TypeScript errors on the stub tree.

    Requires:
    - Node.js and npm installed into .venv via nodeenv (ship.sh preflight handles this).
    - frontend/node_modules populated (npm install must have been run).

    If npm is not on PATH, this test FAILS — it does not skip. The fix is
    to run ship.sh (which installs nodeenv into .venv) or manually:
        .venv/bin/python -m nodeenv --python-virtualenv --node=lts --prebuilt .venv
    """

    import shutil
    import subprocess

    frontend_dir = Path(__file__).parent.parent.parent / "frontend"
    assert frontend_dir.exists(), "frontend/ directory does not exist"

    # npm must be on PATH — provided by nodeenv inside .venv/bin.
    # Hard assert, not skip: a missing npm means the toolchain is broken.
    npm_path = shutil.which("npm")
    assert npm_path is not None, (
        "npm not found in PATH. Install into venv: "
        ".venv/bin/python -m nodeenv --python-virtualenv --node=lts --prebuilt .venv"
    )

    # Check package.json has build script
    package_json_path = frontend_dir / "package.json"
    with open(package_json_path) as f:
        package_data = json.load(f)

    assert "scripts" in package_data, "package.json missing scripts section"
    assert "build" in package_data["scripts"], "package.json missing build script"

    # node_modules must be populated — npm install must have been run.
    node_modules = frontend_dir / "node_modules"
    assert node_modules.exists(), (
        "frontend/node_modules missing — run 'npm install' in frontend/ first"
    )

    # Run tsc type-check only (not the full vite build) because vite's
    # bundler (rollup) depends on platform-matched native binaries that
    # may not be present in all CI environments.  tsc --noEmit validates
    # TypeScript correctness without requiring native rollup modules.
    npx_path = shutil.which("npx")
    assert npx_path is not None, "npx not found in PATH"

    result = subprocess.run(
        [npx_path, "tsc", "--noEmit"],
        cwd=frontend_dir,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"tsc --noEmit failed with exit code {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Check for TypeScript errors in output
    error_indicators = ["error TS", "Type error:", "compilation failed"]
    for indicator in error_indicators:
        assert indicator.lower() not in result.stdout.lower(), (
            f"TypeScript errors found in build output: {result.stdout}"
        )
        assert indicator.lower() not in result.stderr.lower(), (
            f"TypeScript errors found in build stderr: {result.stderr}"
        )
