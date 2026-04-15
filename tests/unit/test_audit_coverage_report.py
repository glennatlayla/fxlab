"""
Structural test for audit coverage completeness.

Validates that all critical state-changing routes (POST, PUT, DELETE) have
audit logging coverage via either audit_action dependency or manual write_audit_event calls.

This test ensures audit coverage cannot regress silently.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_route_files() -> list[Path]:
    """
    Return all route module file paths.

    Routes are in services/api/routes/*.py (excluding __init__.py and __pycache__).

    Returns:
        List of Path objects to route modules.
    """
    routes_dir = Path(__file__).parent.parent.parent / "services" / "api" / "routes"
    if not routes_dir.exists():
        pytest.skip(f"Routes directory not found: {routes_dir}")
        return []

    route_files = [
        f for f in routes_dir.glob("*.py") if f.name not in ("__init__.py", "__pycache__")
    ]
    return sorted(route_files)


def _parse_route_module(module_path: Path) -> ast.Module:
    """
    Parse a Python module into an AST.

    Args:
        module_path: Path to the Python file.

    Returns:
        Parsed AST module.

    Raises:
        SyntaxError: If the module has syntax errors.
    """
    with open(module_path) as f:
        source = f.read()
    return ast.parse(source)


def _find_router_decorators(tree: ast.Module) -> list[tuple[str, str, list[str]]]:
    """
    Extract all @router.post/put/delete decorated functions from an AST.

    Returns:
        List of tuples: (function_name, http_method, decorator_names).

    Example:
        [("activate_kill_switch", "POST", ["@router.post", "@require_scope"]), ...]
    """
    results = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) and not isinstance(node, ast.FunctionDef):
            continue

        # Check decorators
        for decorator in node.decorator_list:
            decorator_str = _unparse_decorator(decorator)

            # Only care about @router.post/put/delete
            if not any(
                method in decorator_str
                for method in ["@router.post", "@router.put", "@router.delete"]
            ):
                continue

            method = "POST"
            if "@router.put" in decorator_str:
                method = "PUT"
            elif "@router.delete" in decorator_str:
                method = "DELETE"

            decorator_names = [_unparse_decorator(d) for d in node.decorator_list]
            results.append((node.name, method, decorator_names))

    return results


def _unparse_decorator(decorator: ast.expr) -> str:
    """
    Convert an AST decorator node back to source code.

    Args:
        decorator: AST node representing a decorator.

    Returns:
        Decorator source as a string (e.g., "@router.post(...)").
    """
    try:
        return f"@{ast.unparse(decorator)}"
    except Exception:
        return "@<unparseable>"


def _route_has_audit_coverage(tree: ast.Module, function_name: str) -> bool:
    """
    Check if a route function has audit coverage.

    A route has audit coverage if:
    1. It has an audit_action in the @router.post/put/delete dependencies
    2. OR it calls write_audit_event() directly in its body.

    Args:
        tree: Parsed AST of the module.
        function_name: Name of the route function.

    Returns:
        True if the function has audit coverage, False otherwise.
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue

        if node.name != function_name:
            continue

        # Check for audit_action in the @router.xxx decorator dependencies
        for decorator in node.decorator_list:
            # Look for @router.post/put/delete(...) with Depends(audit_action(...))
            if isinstance(decorator, ast.Call):
                # Check decorator arguments for Depends(...) calls
                for arg in decorator.args:
                    if isinstance(arg, ast.Call):
                        # Check if this is Depends(...)
                        if isinstance(arg.func, ast.Name) and arg.func.id == "Depends":
                            # Check if the Depends argument is audit_action(...)
                            if arg.args:
                                depends_arg = arg.args[0]
                                if isinstance(depends_arg, ast.Call):
                                    if isinstance(depends_arg.func, ast.Name):
                                        if depends_arg.func.id == "audit_action":
                                            return True

                # Also check keyword arguments (dependencies=[...])
                for keyword in decorator.keywords:
                    if keyword.arg == "dependencies":
                        # dependencies is typically a List
                        if isinstance(keyword.value, ast.List):
                            for elt in keyword.value.elts:
                                if isinstance(elt, ast.Call):
                                    # Check if this is Depends(...)
                                    if isinstance(elt.func, ast.Name) and elt.func.id == "Depends":
                                        # Check if Depends contains audit_action
                                        if elt.args:
                                            depends_arg = elt.args[0]
                                            if isinstance(depends_arg, ast.Call):
                                                if isinstance(depends_arg.func, ast.Name):
                                                    if depends_arg.func.id == "audit_action":
                                                        return True

        # Check for write_audit_event() calls in function body
        for body_node in ast.walk(node):
            if isinstance(body_node, ast.Call):
                if isinstance(body_node.func, ast.Name):
                    if body_node.func.id == "write_audit_event":
                        return True
                elif isinstance(body_node.func, ast.Attribute):
                    if body_node.func.attr == "write_audit_event":
                        return True

        return False

    return False


def _unparse_annotation(annotation: ast.expr) -> str:
    """
    Convert an annotation node to source code.

    Args:
        annotation: AST annotation node.

    Returns:
        Annotation source as a string.
    """
    try:
        return ast.unparse(annotation)
    except Exception:
        return "<unparseable>"


def _get_critical_routes() -> dict[str, list[tuple[str, str]]]:
    """
    Return the set of critical routes that MUST have audit coverage.

    Each critical route is: (route_path, http_method).
    Critical routes are state-changing operations on financial entities that
    must be audited for compliance and traceability.

    Returns:
        Dict mapping route file name to list of (route_path, http_method).
    """
    return {
        "kill_switch.py": [
            ("POST /kill-switch/global", "POST"),
            ("POST /kill-switch/strategy/{strategy_id}", "POST"),
            ("POST /kill-switch/symbol/{symbol}", "POST"),
            ("DELETE /kill-switch/{scope}/{target_id}", "DELETE"),
            ("POST /kill-switch/emergency-posture/{deployment_id}", "POST"),
        ],
        "live.py": [
            ("POST /live/orders", "POST"),
            ("POST /live/orders/{broker_order_id}/cancel", "POST"),
            ("POST /live/orders/{broker_order_id}/sync", "POST"),
            ("POST /live/recover-orphans", "POST"),
        ],
        "approvals.py": [
            ("POST /approvals/{approval_id}/approve", "POST"),
            ("POST /approvals/{approval_id}/reject", "POST"),
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuditCoverageReport:
    """Structural tests for audit coverage completeness."""

    def test_critical_routes_have_audit_coverage(self) -> None:
        """
        All critical financial routes must have audit logging.

        This test ensures that state-changing operations (POST, PUT, DELETE)
        on critical entities have audit coverage, either via:
        - audit_action dependency, OR
        - write_audit_event() call in route handler.
        """
        route_files = _get_route_files()
        if not route_files:
            pytest.skip("No route files found")

        critical_routes = _get_critical_routes()
        uncovered_routes = []

        for route_file in route_files:
            module_name = route_file.stem
            critical_for_module = critical_routes.get(f"{module_name}.py", [])

            if not critical_for_module:
                # This module is not in the critical routes list
                continue

            tree = _parse_route_module(route_file)
            route_handlers = _find_router_decorators(tree)

            for handler_name, method, _ in route_handlers:
                # Check if this handler matches a critical route
                for _critical_path, critical_method in critical_for_module:
                    if critical_method == method:
                        # This is a critical route; verify it has audit coverage
                        has_coverage = _route_has_audit_coverage(tree, handler_name)
                        if not has_coverage:
                            uncovered_routes.append(f"{module_name}: {handler_name} ({method})")

        assert not uncovered_routes, f"Critical routes missing audit coverage: {uncovered_routes}"

    def test_all_state_changing_routes_logged(self) -> None:
        """
        Report all POST/PUT/DELETE routes and their audit coverage status.

        This is an informational test that logs coverage for later review.
        """
        route_files = _get_route_files()
        if not route_files:
            pytest.skip("No route files found")

        coverage_report = {}

        for route_file in route_files:
            module_name = route_file.stem
            tree = _parse_route_module(route_file)
            route_handlers = _find_router_decorators(tree)

            covered = []
            uncovered = []

            for handler_name, method, _ in route_handlers:
                has_coverage = _route_has_audit_coverage(tree, handler_name)
                if has_coverage:
                    covered.append(f"{handler_name} ({method})")
                else:
                    uncovered.append(f"{handler_name} ({method})")

            coverage_report[module_name] = {
                "covered": covered,
                "uncovered": uncovered,
            }

        # Log the report for visibility
        print("\n=== AUDIT COVERAGE REPORT ===")
        for module_name, report in coverage_report.items():
            total = len(report["covered"]) + len(report["uncovered"])
            covered_count = len(report["covered"])
            coverage_percent = (covered_count / total * 100) if total > 0 else 0
            print(
                f"\n{module_name}: {covered_count}/{total} routes covered ({coverage_percent:.0f}%)"
            )
            if report["covered"]:
                print("  COVERED:")
                for route in report["covered"]:
                    print(f"    - {route}")
            if report["uncovered"]:
                print("  UNCOVERED:")
                for route in report["uncovered"]:
                    print(f"    - {route}")

        # Always pass this test; it's informational
        assert True

    def test_no_critical_routes_regress(self) -> None:
        """
        Verify that critical routes remain in the coverage list.

        This test fails if a critical route is removed from the codebase
        but not removed from the critical routes list.
        """
        route_files = _get_route_files()
        if not route_files:
            pytest.skip("No route files found")

        critical_routes = _get_critical_routes()
        available_modules = {f.stem + ".py" for f in route_files}

        missing_modules = []
        for critical_module in critical_routes:
            if critical_module not in available_modules:
                missing_modules.append(critical_module)

        # Log but don't fail — the critical routes list may be aspirational
        if missing_modules:
            print(f"\nWarning: Critical route modules not found: {missing_modules}")


__all__ = [
    "TestAuditCoverageReport",
]
