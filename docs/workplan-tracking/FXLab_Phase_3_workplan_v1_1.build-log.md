
## 2026-03-17T21:58:41Z  M0 S3 RED baseline

Acceptance criteria (0):

RED failures S4 must fix:

```
============================= test session starts ==============================
collected 125 items

tests/acceptance/test_m0_bootstrap.py ............                       [  9%]
tests/unit/test_api_bootstrap.py ..FFFFF.F.                              [ 17%]
tests/unit/test_artifact_storage_interface.py ................           [ 30%]
tests/unit/test_m0_project_structure.py ................................ [ 56%]
........................                                                 [ 75%]
tests/unit/test_metadata_database_interface.py ............              [ 84%]
tests/unit/test_promotions_endpoint.py FFFFFFF                           [ 90%]
tests/unit/test_runs_readiness_endpoint.py FFFFFF                        [ 95%]
tests/unit/test_runs_results_endpoint.py FFFFFF                          [100%]

=================================== FAILURES ===================================
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:60: in test_ac2_runs_results_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/results route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:76: in test_ac2_runs_readiness_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/readiness route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
_________________ test_ac2_promotions_request_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:98: in test_ac2_promotions_request_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: POST /promotions/request route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
__________________ test_ac2_approvals_approve_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:119: in test_ac2_approvals_approve_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: POST /approvals/{id}/approve route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
________________________ test_ac2_audit_endpoint_exists ________________________
tests/unit/test_api_bootstrap.py:134: in test_ac2_audit_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /audit route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
___________________ test_ac3_application_has_openapi_schema ____________________
tests/unit/test_api_bootstrap.py:170: in test_ac3_application_has_openapi_schema
    assert "/runs/{run_id}/results" in paths, \
E   AssertionError: Results endpoint must appear in OpenAPI schema
E   assert '/runs/{run_id}/results' in {'/health': {'get': {'description': 'Health check endpoint.', 'operationId': 'health_check_health_get', 'responses': {...': {'content': {'application/json': {...}}, 'description': 'Successful Response'}}, 'summary': 'Health Dependencies'}}}
________________ test_promotions_endpoint_requires_candidate_id ________________
tests/unit/test_promotions_endpoint.py:32: in test_promotions_endpoint_requires_candidate_id
    assert response.status_code == 422, \
E   AssertionError: Request without candidate_id must be rejected
E   assert 404 == 422
E    +  where 404 = <Response [404 Not Found]>.status_code
_____________ test_promotions_endpoint_requires_target_environment _____________
tests/unit/test_promotions_endpoint.py:49: in test_promotions_endpoint_requires_target_environment
    assert response.status_code == 422, \
E   AssertionError: Request without target_environment must be rejected
E   assert 404 == 422
E    +  where 404 = <Response [404 Not Found]>.status_code
________________ test_promotions_endp
```

## 2026-03-17T22:06:58Z  M0 S3 RED baseline

Acceptance criteria (14):
  - `frontend/` directory exists at project root
  - `frontend/package.json` lists all required Phase 3 frontend dependencies
  - `frontend/tsconfig.json` exists with `strict: true` enabled
  - `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/router.tsx` exist
  - `frontend/src/api/client.ts` exists
  - `frontend/src/auth/AuthProvider.tsx`, `useAuth.ts`, and `permissions.ts` exist
  - `frontend/src/components/`, `features/`, `pages/`, `hooks/` directories exist
  - `npm run build` exits 0 with zero TypeScript errors on the stub tree
  - Phase 1 `/health` endpoint returns `success: true` (importability check)
  - Phase 2 `services/api/routes/strategies.py` is importable without errors
  - `services/api/routes/charts.py` stub exists (M23/M24 will implement it)
  - `services/api/routes/governance.py` stub exists
  - `services/api/routes/queues.py` stub exists
  - `services/api/routes/feed_health.py` stub exists

RED failures S4 must fix:

```
============================= test session starts ==============================
collected 139 items

tests/acceptance/test_m0_bootstrap.py ............                       [  8%]
tests/integration/test_m0_backend_api_importability.py ..FFFF            [ 12%]
tests/unit/test_api_bootstrap.py ..FFFFF.F.                              [ 20%]
tests/unit/test_artifact_storage_interface.py ................           [ 31%]
tests/unit/test_m0_frontend_structure.py FFFFFFFF                        [ 37%]
tests/unit/test_m0_project_structure.py ................................ [ 60%]
........................                                                 [ 77%]
tests/unit/test_metadata_database_interface.py ............              [ 86%]
tests/unit/test_promotions_endpoint.py FFFFFFF                           [ 91%]
tests/unit/test_runs_readiness_endpoint.py FFFFFF                        [ 95%]
tests/unit/test_runs_results_endpoint.py FFFFFF                          [100%]

=================================== FAILURES ===================================
______________________ test_ac11_charts_route_stub_exists ______________________
tests/integration/test_m0_backend_api_importability.py:44: in test_ac11_charts_route_stub_exists
    from services.api.routes import charts
E   ImportError: cannot import name 'charts' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:46: in test_ac11_charts_route_stub_exists
    pytest.fail(f"Cannot import services.api.routes.charts: {e}")
E   Failed: Cannot import services.api.routes.charts: cannot import name 'charts' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)
____________________ test_ac12_governance_route_stub_exists ____________________
tests/integration/test_m0_backend_api_importability.py:61: in test_ac12_governance_route_stub_exists
    from services.api.routes import governance
E   ImportError: cannot import name 'governance' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:63: in test_ac12_governance_route_stub_exists
    pytest.fail(f"Cannot import services.api.routes.governance: {e}")
E   Failed: Cannot import services.api.routes.governance: cannot import name 'governance' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)
______________________ test_ac13_queues_route_stub_exists ______________________
tests/integration/test_m0_backend_api_importability.py:78: in test_ac13_queues_route_stub_exists
    from services.api.routes import queues
E   ImportError: cannot import name 'queues' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:80: in test_ac13_queues_route_stub_exists
    pytest.fail(f"Cannot import services.api.routes.queues: {e}")
E   Failed: Cannot import services.api.routes.queues: cannot import name 'queues' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)
___________________ test_ac14_feed_health_route_stub_exists ____________________
tests/integration/test_m0_backend_api_importability.py:95: in test_ac14_feed_health_route_stub_exists
    from services.api.routes import feed_health
E   ImportError: cannot import name 'feed_health' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:
```

## 2026-03-17T22:09:26Z  S4 M0 — round 1/3, 6 file(s)


## 2026-03-17T22:09:26Z  File: tests/integration/test_m0_backend_api_importability.py

```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py ..FFFF            [100%]

=================================== FAILURES ===================================
______________________ test_ac11_charts_route_stub_exists ______________________
tests/integration/test_m0_backend_api_importability.py:44: in test_ac11_charts_route_stub_exists
    from services.api.routes import charts
E   ImportError: cannot import name 'charts' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:46: in test_ac11_charts_route_stub_exists
    pytest.fail(f"Cannot import services.api.routes.charts: {e}")
E   Failed: Cannot import services.api.routes.charts: cannot import name 'charts' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)
____________________ test_ac12_governance_route_stub_exists ____________________
tests/integration/test_m0_backend_api_importability.py:61: in test_ac12_governance_route_stub_exists
    from services.api.routes import governance
E   ImportError: cannot import name 'governance' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:63: in test_ac12_governance_route_stub_exists
    pytest.fail(f"Cannot import services.api.routes.governance: {e}")
E   Failed: Cannot import services.api.routes.governance: cannot import name 'governance' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)
______________________ test_ac13_queues_route_stub_exists ______________________
tests/integration/test_m0_backend_api_importability.py:78: in test_ac13_queues_route_stub_exists
    from services.api.routes import queues
E   ImportError: cannot import name 'queues' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:80: in test_ac13_queues_route_stub_exists
    pytest.fail(f"Cannot import services.api.routes.queues: {e}")
E   Failed: Cannot import services.api.routes.queues: cannot import name 'queues' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)
___________________ test_ac14_feed_health_route_stub_exists ____________________
tests/integration/test_m0_backend_api_importability.py:95: in test_ac14_feed_health_route_stub_exists
    from services.api.routes import feed_health
E   ImportError: cannot import name 'feed_health' from 'services.api.routes' (/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/routes/__init__.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:97: in test_ac14_feed_health_route_stub_exists
... (121 more lines truncated)
```
    wrote: services/api/routes/charts.py
    wrote: services/api/routes/governance.py
    wrote: services/api/routes/queues.py
    wrote: services/api/routes/feed_health.py

## 2026-03-17T22:09:36Z  File: tests/unit/test_api_bootstrap.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py ..FFFFF.F.                              [100%]

=================================== FAILURES ===================================
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:60: in test_ac2_runs_results_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/results route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:76: in test_ac2_runs_readiness_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/readiness route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
_________________ test_ac2_promotions_request_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:98: in test_ac2_promotions_request_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: POST /promotions/request route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
__________________ test_ac2_approvals_approve_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:119: in test_ac2_approvals_approve_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: POST /approvals/{id}/approve route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
________________________ test_ac2_audit_endpoint_exists ________________________
tests/unit/test_api_bootstrap.py:134: in test_ac2_audit_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /audit route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
___________________ test_ac3_application_has_openapi_schema ____________________
tests/unit/test_api_bootstrap.py:170: in test_ac3_application_has_openapi_schema
    assert "/runs/{run_id}/results" in paths, \
E   AssertionError: Results endpoint must appear in OpenAPI schema
... (126 more lines truncated)
```
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/routes/approvals.py
    wrote: services/api/routes/audit.py
    wrote: services/api/main.py

## 2026-03-17T22:09:58Z  File: tests/unit/test_m0_frontend_structure.py

```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py FFFFFFFF                        [100%]

=================================== FAILURES ===================================
______________________ test_ac1_frontend_directory_exists ______________________
tests/unit/test_m0_frontend_structure.py:23: in test_ac1_frontend_directory_exists
    assert frontend_dir.exists(), "frontend/ directory does not exist"
E   AssertionError: frontend/ directory does not exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('/Users/gjohnson/Documents/Coding Projects/fxlab/frontend').exists
________________ test_ac2_package_json_exists_with_dependencies ________________
tests/unit/test_m0_frontend_structure.py:30: in test_ac2_package_json_exists_with_dependencies
    assert package_json_path.exists(), "frontend/package.json does not exist"
E   AssertionError: frontend/package.json does not exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('/Users/gjohnson/Documents/Coding Projects/fxlab/frontend/package.json').exists
__________________ test_ac3_tsconfig_exists_with_strict_mode ___________________
tests/unit/test_m0_frontend_structure.py:58: in test_ac3_tsconfig_exists_with_strict_mode
    assert tsconfig_path.exists(), "frontend/tsconfig.json does not exist"
E   AssertionError: frontend/tsconfig.json does not exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('/Users/gjohnson/Documents/Coding Projects/fxlab/frontend/tsconfig.json').exists
_______________________ test_ac4_core_entry_files_exist ________________________
tests/unit/test_m0_frontend_structure.py:80: in test_ac4_core_entry_files_exist
    assert file_path.exists(), f"frontend/src/{filename} does not exist"
E   AssertionError: frontend/src/main.tsx does not exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('/Users/gjohnson/Documents/Coding Projects/fxlab/frontend/src/main.tsx').exists
__________________________ test_ac5_api_client_exists __________________________
tests/unit/test_m0_frontend_structure.py:87: in test_ac5_api_client_exists
    assert api_client_path.exists(), "frontend/src/api/client.ts does not exist"
E   AssertionError: frontend/src/api/client.ts does not exist
E   assert False
E    +  where False = exists()
... (154 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: frontend/package.json
    wrote: frontend/tsconfig.json
    wrote: frontend/tsconfig.node.json
    wrote: frontend/vite.config.ts
    wrote: frontend/index.html
    wrote: frontend/src/main.tsx
    wrote: frontend/src/App.tsx
    wrote: frontend/src/router.tsx
    wrote: frontend/src/api/client.ts
    wrote: frontend/src/components/auth/LoginPage.tsx
    wrote: frontend/src/components/auth/ProtectedRoute.tsx
    wrote: frontend/src/pages/.gitkeep
    wrote: frontend/src/hooks/.gitkeep
    wrote: frontend/src/types/.gitkeep
    wrote: frontend/src/utils/.gitkeep
    wrote: frontend/.gitignore
    retry 1 for tests/unit/test_m0_frontend_structure.py
```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .....FFF                        [100%]

=================================== FAILURES ===================================
________________________ test_ac6_auth_components_exist ________________________
tests/unit/test_m0_frontend_structure.py:103: in test_ac6_auth_components_exist
    assert file_path.exists(), f"frontend/src/auth/{filename} does not exist"
E   AssertionError: frontend/src/auth/AuthProvider.tsx does not exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('/Users/gjohnson/Documents/Coding Projects/fxlab/frontend/src/auth/AuthProvider.tsx').exists
_________________ test_ac7_frontend_directory_structure_exists _________________
tests/unit/test_m0_frontend_structure.py:120: in test_ac7_frontend_directory_structure_exists
    assert dir_path.exists(), f"frontend/src/{dirname}/ directory does not exist"
E   AssertionError: frontend/src/features/ directory does not exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('/Users/gjohnson/Documents/Coding Projects/fxlab/frontend/src/features').exists
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
... (118 more lines truncated)
```
    wrote (retry 1): frontend/src/auth/AuthProvider.tsx
    wrote (retry 1): frontend/src/auth/useAuth.ts
    wrote (retry 1): frontend/src/features/.gitkeep
    wrote (retry 1): frontend/package.json
    wrote (retry 1): frontend/src/features/strategy/.gitkeep
    wrote (retry 1): frontend/src/features/runs/.gitkeep
    wrote (retry 1): frontend/src/features/feeds/.gitkeep
    wrote (retry 1): frontend/src/features/approvals/.gitkeep
    wrote (retry 1): frontend/src/features/audit/.gitkeep
    wrote (retry 1): frontend/src/components/.gitkeep
    wrote (retry 1): frontend/src/hooks/.gitkeep
    wrote (retry 1): frontend/src/utils/.gitkeep
    wrote (retry 1): frontend/src/types/.gitkeep
```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .....F.F                        [100%]

=================================== FAILURES ===================================
________________________ test_ac6_auth_components_exist ________________________
tests/unit/test_m0_frontend_structure.py:103: in test_ac6_auth_components_exist
    assert file_path.exists(), f"frontend/src/auth/{filename} does not exist"
E   AssertionError: frontend/src/auth/permissions.ts does not exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('/Users/gjohnson/Documents/Coding Projects/fxlab/frontend/src/auth/permissions.ts').exists
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            44     44     0%   7-97
libs/contracts/base.py                              9      9     0%   2-18
... (110 more lines truncated)
```

## 2026-03-17T22:10:54Z  File: tests/unit/test_promotions_endpoint.py

```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py ..FFFFF                           [100%]

=================================== FAILURES ===================================
________________ test_promotions_endpoint_validates_ulid_format ________________
tests/unit/test_promotions_endpoint.py:67: in test_promotions_endpoint_validates_ulid_format
    assert response.status_code == 422, \
E   AssertionError: Invalid ULID format must be rejected
E   assert 200 == 422
E    +  where 200 = <Response [200 OK]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:10:55 [info     ] request_promotion.entry        candidate_id=not-a-ulid target_environment=paper
_____________ test_promotions_endpoint_returns_job_id_immediately ______________
tests/unit/test_promotions_endpoint.py:88: in test_promotions_endpoint_returns_job_id_immediately
    with patch("services.api.main.submit_promotion_request") as mock_submit:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'submit_promotion_request'
_________________ test_promotions_endpoint_creates_audit_event _________________
tests/unit/test_promotions_endpoint.py:113: in test_promotions_endpoint_creates_audit_event
    with patch("services.api.main.submit_promotion_request") as mock_submit, \
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'submit_promotion_request'
__________ test_promotions_endpoint_validates_target_environment_enum __________
tests/unit/test_promotions_endpoint.py:139: in test_promotions_endpoint_validates_target_environment_enum
    assert response.status_code == 422, \
E   AssertionError: Invalid target environment must be rejected
E   assert 200 == 422
E    +  where 200 = <Response [200 OK]>.status_code
... (139 more lines truncated)
```
    wrote: libs/contracts/promotion.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/dependencies.py
    wrote: services/api/main.py
    wrote: libs/contracts/audit.py
    wrote: tests/unit/conftest.py
    wrote: libs/contracts/enums.py
    wrote: services/api/main.py
    wrote: services/api/__init__.py
    retry 1 for tests/unit/test_promotions_endpoint.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py ...FF.F                           [100%]

=================================== FAILURES ===================================
_____________ test_promotions_endpoint_returns_job_id_immediately ______________
tests/unit/test_promotions_endpoint.py:91: in test_promotions_endpoint_returns_job_id_immediately
    response = client.post("/promotions/request", json=payload)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/starlette/testclient.py:546: in post
    return super().post(
.venv/lib/python3.12/site-packages/httpx/_client.py:1144: in post
    return self.request(
.venv/lib/python3.12/site-packages/starlette/testclient.py:445: in request
    return super().request(
.venv/lib/python3.12/site-packages/httpx/_client.py:825: in request
    return self.send(request, auth=auth, follow_redirects=follow_redirects)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/httpx/_client.py:914: in send
    response = self._send_handling_auth(
.venv/lib/python3.12/site-packages/httpx/_client.py:942: in _send_handling_auth
    response = self._send_handling_redirects(
.venv/lib/python3.12/site-packages/httpx/_client.py:979: in _send_handling_redirects
    response = self._send_single_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/httpx/_client.py:1014: in _send_single_request
    response = transport.handle_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/starlette/testclient.py:348: in handle_request
    raise exc
.venv/lib/python3.12/site-packages/starlette/testclient.py:345: in handle_request
    portal.call(self.app, scope, receive, send)
.venv/lib/python3.12/site-packages/anyio/from_thread.py:334: in call
    return cast(T_Retval, self.start_task_soon(func, *args).result())
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/concurrent/futures/_base.py:456: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/concurrent/futures/_base.py:401: in __get_result
... (196 more lines truncated)
```
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py ....FFF                           [100%]

=================================== FAILURES ===================================
_________________ test_promotions_endpoint_creates_audit_event _________________
tests/unit/test_promotions_endpoint.py:114: in test_promotions_endpoint_creates_audit_event
    patch("services.api.main.audit_service") as mock_audit:
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'audit_service'
__________ test_promotions_endpoint_validates_target_environment_enum __________
tests/unit/test_promotions_endpoint.py:139: in test_promotions_endpoint_validates_target_environment_enum
    assert response.status_code == 422, \
E   AssertionError: Invalid target environment must be rejected
E   assert 202 == 422
E    +  where 202 = <Response [202 Accepted]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:12:51 [info     ] promotion_request_received     candidate_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V requester_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0W target_environment=invalid_environment
2026-03-17 18:12:51 [info     ] promotion_request_submitted    candidate_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V requester_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0W target_environment=invalid_environment
2026-03-17 18:12:51 [info     ] audit_event_created            action=promotion_requested
2026-03-17 18:12:51 [info     ] promotion_job_created          candidate_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V job_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0X
____________________ test_promotions_endpoint_enforces_rbac ____________________
tests/unit/test_promotions_endpoint.py:155: in test_promotions_endpoint_enforces_rbac
    with patch("services.api.main.check_permission") as mock_check:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'check_permission'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

... (124 more lines truncated)
```

## 2026-03-17T22:12:52Z  File: tests/unit/test_runs_readiness_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py FFFFFF                        [100%]

=================================== FAILURES ===================================
_________________ test_readiness_endpoint_requires_valid_ulid __________________
tests/unit/test_runs_readiness_endpoint.py:28: in test_readiness_endpoint_requires_valid_ulid
    assert response.status_code in [400, 422], \
E   AssertionError: Invalid ULID must be rejected
E   assert 404 in [400, 422]
E    +  where 404 = <Response [404 Not Found]>.status_code
___________ test_readiness_endpoint_returns_404_for_nonexistent_run ____________
tests/unit/test_runs_readiness_endpoint.py:40: in test_readiness_endpoint_returns_404_for_nonexistent_run
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_readiness_report'
_____________ test_readiness_response_includes_grade_and_blockers ______________
tests/unit/test_runs_readiness_endpoint.py:63: in test_readiness_response_includes_grade_and_blockers
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_readiness_report'
_____________ test_readiness_blockers_include_owner_and_next_step ______________
tests/unit/test_runs_readiness_endpoint.py:96: in test_readiness_blockers_include_owner_and_next_step
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
... (148 more lines truncated)
```
    wrote: services/api/routes/runs.py
    wrote: services/api/main.py
    wrote: libs/contracts/readiness.py
    wrote: services/api/routes/runs.py
    wrote: services/api/main.py
    retry 1 for tests/unit/test_runs_readiness_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py ..FF.F                        [100%]

=================================== FAILURES ===================================
_____________ test_readiness_response_includes_grade_and_blockers ______________
tests/unit/test_runs_readiness_endpoint.py:69: in test_readiness_response_includes_grade_and_blockers
    assert "readiness_grade" in data, \
E   AssertionError: Response must include readiness_grade
E   assert 'readiness_grade' in {'detail': 'Run 01HQ7X9Z8K3M4N5P6Q7R8S9T0V not found'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:13:28 [info     ] get_run_readiness.called       run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:13:28 [info     ] get_readiness_report.called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:13:28 [info     ] get_run_readiness.not_found    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
_____________ test_readiness_blockers_include_owner_and_next_step ______________
tests/unit/test_runs_readiness_endpoint.py:102: in test_readiness_blockers_include_owner_and_next_step
    blockers = data["blockers"]
               ^^^^^^^^^^^^^^^^
E   KeyError: 'blockers'
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:13:28 [info     ] get_run_readiness.called       run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:13:28 [info     ] get_readiness_report.called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:13:28 [info     ] get_run_readiness.not_found    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
_______________ test_readiness_report_includes_scoring_evidence ________________
tests/unit/test_runs_readiness_endpoint.py:155: in test_readiness_report_includes_scoring_evidence
    assert "scoring_evidence" in data, \
E   AssertionError: Readiness report must include scoring evidence
E   assert 'scoring_evidence' in {'detail': 'Run 01HQ7X9Z8K3M4N5P6Q7R8S9T0V not found'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:13:28 [info     ] get_run_readiness.called       run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:13:28 [info     ] get_readiness_report.called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:13:28 [info     ] get_run_readiness.not_found    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
... (120 more lines truncated)
```
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/runs.py

## 2026-03-17T22:14:19Z  File: tests/unit/test_runs_results_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py FFFFFF                          [100%]

=================================== FAILURES ===================================
_______________ test_results_endpoint_requires_valid_ulid_format _______________
tests/unit/test_runs_results_endpoint.py:29: in test_results_endpoint_requires_valid_ulid_format
    assert response.status_code in [400, 422], \
E   AssertionError: Invalid ULID format must be rejected with 400 or 422
E   assert 404 in [400, 422]
E    +  where 404 = <Response [404 Not Found]>.status_code
____________ test_results_endpoint_returns_404_for_nonexistent_run _____________
tests/unit/test_runs_results_endpoint.py:42: in test_results_endpoint_returns_404_for_nonexistent_run
    with patch("services.api.main.get_run_results") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_run_results'
________________ test_results_endpoint_returns_structured_json _________________
tests/unit/test_runs_results_endpoint.py:66: in test_results_endpoint_returns_structured_json
    with patch("services.api.main.get_run_results") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_run_results'
________________ test_results_endpoint_includes_metadata_fields ________________
tests/unit/test_runs_results_endpoint.py:95: in test_results_endpoint_includes_metadata_fields
    with patch("services.api.main.get_run_results") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
... (152 more lines truncated)
```
    wrote: services/api/routes/runs.py
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
```
============================= test session starts ==============================
collected 139 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [  8%]
tests/integration/test_m0_backend_api_importability.py F.....            [ 12%]
tests/unit/test_api_bootstrap.py ..FFFFF.F.                              [ 20%]
tests/unit/test_artifact_storage_interface.py ................           [ 31%]
tests/unit/test_m0_frontend_structure.py .....F.F                        [ 37%]
tests/unit/test_m0_project_structure.py ...............................F [ 60%]
.F......................                                                 [ 77%]
tests/unit/test_metadata_database_interface.py ............              [ 86%]
tests/unit/test_promotions_endpoint.py FFFFFFF                           [ 91%]
tests/unit/test_runs_readiness_endpoint.py FFFFFF                        [ 95%]
tests/unit/test_runs_results_endpoint.py ......                          [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/results'}
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'ok'}
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:60: in test_ac2_runs_results_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/results route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:14:45 [info     ] get_run_results_endpoint.entry run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:14:45 [info     ] get_run_results.entry          run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:14:45 [info     ] get_run_results_endpoint.not_found run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
... (335 more lines truncated)
```

## 2026-03-17T22:14:47Z  S4 M0 — round 2/3, 7 file(s)


## 2026-03-17T22:14:47Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/results'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            34     34     0%   4-51
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            29      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       67     67     0%   8-171
... (101 more lines truncated)
```
    wrote: libs/contracts/enums.py
    wrote: services/api/routes/health.py
    wrote: services/api/main.py
    retry 1 for tests/acceptance/test_m0_bootstrap.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:6: in <module>
    from services.api.routes import health
services/api/routes/health.py:6: in <module>
    from libs.contracts.health import HealthCheckResponse, DependencyHealth
E   ImportError: cannot import name 'HealthCheckResponse' from 'libs.contracts.health' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/health.py)
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            34     34     0%   4-51
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            37      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       67     67     0%   8-171
libs/contracts/health.py                           10      0   100%
... (99 more lines truncated)
```
    wrote (retry 1): libs/contracts/health.py
    wrote (retry 1): services/api/routes/health.py
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:15:17 [info     ] fastapi.app.initialized
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            34     34     0%   4-51
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            37      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       67     67     0%   8-171
libs/contracts/health.py                           12      0   100%
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
... (97 more lines truncated)
```

## 2026-03-17T22:15:18Z  File: tests/integration/test_m0_backend_api_importability.py

```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'dependencies': [], 'status': 'healthy', 'version': '0.1.0'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:15:19 [info     ] fastapi.app.initialized
2026-03-17 18:15:19 [info     ] health_check.entry
2026-03-17 18:15:19 [info     ] health_check.success           status=healthy
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            34     34     0%   4-51
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            37     37     0%   2-59
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       67     67     0%   8-171
... (100 more lines truncated)
```
    wrote: services/api/routes/health.py
    retry 1 for tests/integration/test_m0_backend_api_importability.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:6: in <module>
    from services.api.routes import health
services/api/routes/health.py:6: in <module>
    from libs.contracts.health import HealthCheckResult
E   ImportError: cannot import name 'HealthCheckResult' from 'libs.contracts.health' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/health.py)

During handling of the above exception, another exception occurred:
tests/integration/test_m0_backend_api_importability.py:17: in test_ac9_phase1_health_endpoint_returns_success
    pytest.fail(f"Cannot import services.api.main: {e}")
E   Failed: Cannot import services.api.main: cannot import name 'HealthCheckResult' from 'libs.contracts.health' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/health.py)
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            34     34     0%   4-51
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            37     37     0%   2-59
... (104 more lines truncated)
```
    wrote (retry 1): libs/contracts/health.py
    wrote (retry 1): services/api/routes/health.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/strategies.py
    wrote (retry 1): services/api/routes/charts.py
    wrote (retry 1): services/api/routes/governance.py
    wrote (retry 1): services/api/routes/queues.py
    wrote (retry 1): services/api/routes/research.py
    wrote (retry 1): services/__init__.py
    wrote (retry 1): services/api/__init__.py

## 2026-03-17T22:15:44Z  File: tests/unit/test_api_bootstrap.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py ..FFFFF.F.                              [100%]

=================================== FAILURES ===================================
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:60: in test_ac2_runs_results_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/results route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:76: in test_ac2_runs_readiness_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/readiness route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
_________________ test_ac2_promotions_request_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:98: in test_ac2_promotions_request_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: POST /promotions/request route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
__________________ test_ac2_approvals_approve_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:119: in test_ac2_approvals_approve_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: POST /approvals/{id}/approve route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
________________________ test_ac2_audit_endpoint_exists ________________________
tests/unit/test_api_bootstrap.py:134: in test_ac2_audit_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /audit route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
___________________ test_ac3_application_has_openapi_schema ____________________
tests/unit/test_api_bootstrap.py:170: in test_ac3_application_has_openapi_schema
    assert "/runs/{run_id}/results" in paths, \
E   AssertionError: Results endpoint must appear in OpenAPI schema
... (132 more lines truncated)
```
    wrote: services/api/__init__.py
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/routes/approvals.py
    wrote: services/api/routes/audit.py
    retry 1 for tests/unit/test_api_bootstrap.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:24: in <module>
    from services.api.routes import runs, promotions, approvals, audit
services/api/routes/runs.py:8: in <module>
    from libs.contracts.optimization import OptimizationResultsResponse
E   ImportError: cannot import name 'OptimizationResultsResponse' from 'libs.contracts.optimization' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/optimization.py)

During handling of the above exception, another exception occurred:
tests/unit/test_api_bootstrap.py:27: in test_ac1_fastapi_application_module_exists
    pytest.fail(f"services/api/main.py not found: {e}")
E   Failed: services/api/main.py not found: cannot import name 'OptimizationResultsResponse' from 'libs.contracts.optimization' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/optimization.py)
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:24: in <module>
    from services.api.routes import runs, promotions, approvals, audit
services/api/routes/runs.py:8: in <module>
    from libs.contracts.optimization import OptimizationResultsResponse
E   ImportError: cannot import name 'OptimizationResultsResponse' from 'libs.contracts.optimization' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/optimization.py)
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:24: in <module>
    from services.api.routes import runs, promotions, approvals, audit
services/api/routes/runs.py:8: in <module>
    from libs.contracts.optimization import OptimizationResultsResponse
E   ImportError: cannot import name 'OptimizationResultsResponse' from 'libs.contracts.optimization' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/optimization.py)
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:70: in test_ac2_runs_readiness_endpoint_exists
    from services.api.main import app
services/api/main.py:24: in <module>
    from services.api.routes import runs, promotions, approvals, audit
... (206 more lines truncated)
```
    wrote (retry 1): libs/contracts/optimization.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/routes/approvals.py
    wrote (retry 1): services/api/routes/audit.py
    wrote (retry 1): libs/contracts/readiness.py
    wrote (retry 1): libs/contracts/promotion.py
    wrote (retry 1): libs/contracts/governance.py
    wrote (retry 1): libs/contracts/audit.py
    wrote (retry 1): libs/contracts/enums.py

## 2026-03-17T22:17:03Z  File: tests/unit/test_m0_frontend_structure.py

```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .....F.F                        [100%]

=================================== FAILURES ===================================
________________________ test_ac6_auth_components_exist ________________________
tests/unit/test_m0_frontend_structure.py:103: in test_ac6_auth_components_exist
    assert file_path.exists(), f"frontend/src/auth/{filename} does not exist"
E   AssertionError: frontend/src/auth/permissions.ts does not exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('/Users/gjohnson/Documents/Coding Projects/fxlab/frontend/src/auth/permissions.ts').exists
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      9     0%   2-18
... (113 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: frontend/src/auth/permissions.ts
    wrote: frontend/package.json
    wrote: frontend/vite.config.ts
    wrote: frontend/index.html
    retry 1 for tests/unit/test_m0_frontend_structure.py
```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .......F                        [100%]

=================================== FAILURES ===================================
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      9     0%   2-18
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            30     30     0%   5-52
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
... (105 more lines truncated)
```
    wrote (retry 1): frontend/.npmrc
    wrote (retry 1): frontend/.gitignore
    wrote (retry 1): frontend/README.md
    wrote (retry 1): frontend/package.json
    wrote (retry 1): frontend/src/main.tsx
    wrote (retry 1): frontend/src/App.tsx
    wrote (retry 1): frontend/src/router.tsx
    wrote (retry 1): frontend/src/api/client.ts
    wrote (retry 1): frontend/src/components/Layout.tsx
    wrote (retry 1): frontend/src/pages/Dashboard.tsx
    wrote (retry 1): frontend/src/pages/StrategyStudio.tsx
    wrote (retry 1): frontend/src/pages/Runs.tsx
    wrote (retry 1): frontend/src/pages/Feeds.tsx
    wrote (retry 1): frontend/src/pages/Approvals.tsx
    wrote (retry 1): frontend/src/pages/Overrides.tsx
    wrote (retry 1): frontend/src/pages/Audit.tsx
    wrote (retry 1): frontend/src/pages/Queues.tsx
    wrote (retry 1): frontend/src/pages/Artifacts.tsx
    wrote (retry 1): frontend/src/index.css
    wrote (retry 1): frontend/tsconfig.json
    wrote (retry 1): frontend/tsconfig.node.json
    wrote (retry 1): frontend/vite.config.ts
    wrote (retry 1): frontend/index.html
```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py ..F....F                        [100%]

=================================== FAILURES ===================================
__________________ test_ac3_tsconfig_exists_with_strict_mode ___________________
tests/unit/test_m0_frontend_structure.py:61: in test_ac3_tsconfig_exists_with_strict_mode
    tsconfig_data = json.load(f)
                    ^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/json/__init__.py:293: in load
    return loads(fp.read(),
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/json/__init__.py:346: in loads
    return _default_decoder.decode(s)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/json/decoder.py:338: in decode
    obj, end = self.raw_decode(s, idx=_w(s, 0).end())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/json/decoder.py:354: in raw_decode
    obj, end = self.scan_once(s, idx)
               ^^^^^^^^^^^^^^^^^^^^^^
E   json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 10 column 5 (char 207)
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
... (122 more lines truncated)
```

## 2026-03-17T22:18:27Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:5: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:4: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:8: in <module>
    from libs.contracts.enums import StrategyType
E   ImportError: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:5: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:4: in <module>
    from libs.contracts.research import ExperimentDefinition, ExperimentPlan
libs/contracts/research.py:8: in <module>
    from libs.contracts.enums import ResearchPhase
E   ImportError: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
================================ tests coverage ================================
... (126 more lines truncated)
```
    wrote: libs/contracts/enums.py
    wrote: libs/experiment_plan/interfaces/__init__.py
    retry 1 for tests/unit/test_m0_project_structure.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ................................ [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:5: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:5: in <module>
    from libs.contracts.research import ExperimentPlan, ExperimentRequest
libs/contracts/research.py:8: in <module>
    from libs.contracts.enums import ResearchPhase
E   ImportError: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
... (109 more lines truncated)
```
    wrote (retry 1): libs/contracts/enums.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:5: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:4: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:8: in <module>
    from libs.contracts.enums import StrategyType
E   ImportError: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:5: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:5: in <module>
    from libs.contracts.research import ExperimentPlan, ExperimentRequest
E   ImportError: cannot import name 'ExperimentRequest' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ExperimentRequest' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

... (124 more lines truncated)
```

## 2026-03-17T22:18:46Z  File: tests/unit/test_promotions_endpoint.py

```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:28: in <module>
    from services.api.routes import runs, promotions, approvals, audit
services/api/routes/runs.py:8: in <module>
    from libs.contracts.optimization import OptimizationResultsResponse
libs/contracts/optimization.py:11: in <module>
    from libs.contracts.enums import OptimizationStatus
E   ImportError: cannot import name 'OptimizationStatus' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:28: in <module>
    from services.api.routes import runs, promotions, approvals, audit
services/api/routes/runs.py:8: in <module>
    from libs.contracts.optimization import OptimizationResultsResponse
libs/contracts/optimization.py:11: in <module>
    from libs.contracts.enums import OptimizationStatus
E   ImportError: cannot import name 'OptimizationStatus' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:28: in <module>
    from services.api.routes import runs, promotions, approvals, audit
services/api/routes/runs.py:8: in <module>
    from libs.contracts.optimization import OptimizationResultsResponse
libs/contracts/optimization.py:11: in <module>
    from libs.contracts.enums import OptimizationStatus
E   ImportError: cannot import name 'OptimizationStatus' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:28: in <module>
... (168 more lines truncated)
```
    wrote: libs/contracts/enums.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/main.py
    retry 1 for tests/unit/test_promotions_endpoint.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:27: in <module>
    from services.api.routes import promotions
services/api/routes/promotions.py:6: in <module>
    from libs.contracts.promotion import PromotionRequestPayload, PromotionRequestResponse
E   ImportError: cannot import name 'PromotionRequestPayload' from 'libs.contracts.promotion' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/promotion.py)
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:27: in <module>
    from services.api.routes import promotions
services/api/routes/promotions.py:6: in <module>
    from libs.contracts.promotion import PromotionRequestPayload, PromotionRequestResponse
E   ImportError: cannot import name 'PromotionRequestPayload' from 'libs.contracts.promotion' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/promotion.py)
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:27: in <module>
    from services.api.routes import promotions
services/api/routes/promotions.py:6: in <module>
    from libs.contracts.promotion import PromotionRequestPayload, PromotionRequestResponse
E   ImportError: cannot import name 'PromotionRequestPayload' from 'libs.contracts.promotion' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/promotion.py)
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:27: in <module>
    from services.api.routes import promotions
services/api/routes/promotions.py:6: in <module>
    from libs.contracts.promotion import PromotionRequestPayload, PromotionRequestResponse
E   ImportError: cannot import name 'PromotionRequestPayload' from 'libs.contracts.promotion' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/promotion.py)
________ ERROR at setup of test_promotions_endpoint_creates_audit_event ________
tests/unit/test_promotions_endpoint.py:15: in client
... (154 more lines truncated)
```
    wrote (retry 1): libs/contracts/promotion.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): libs/contracts/enums.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py ...FF.F                           [100%]

=================================== FAILURES ===================================
_____________ test_promotions_endpoint_returns_job_id_immediately ______________
tests/unit/test_promotions_endpoint.py:97: in test_promotions_endpoint_returns_job_id_immediately
    assert "job_id" in data, \
E   AssertionError: Response must include job_id for async tracking
E   assert 'job_id' in {'data': {'job_id': '01HQ7X9Z8K3M4N5P6Q7R8S9T0X', 'status': 'pending'}, 'error': None, 'success': True}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:19:24 [info     ] promotion_request_received     candidate_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V requester_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0W target_environment=paper
2026-03-17 18:19:24 [info     ] promotion_request_submitted    job_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0X status=pending
_________________ test_promotions_endpoint_creates_audit_event _________________
tests/unit/test_promotions_endpoint.py:114: in test_promotions_endpoint_creates_audit_event
    patch("services.api.main.audit_service") as mock_audit:
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'audit_service'
____________________ test_promotions_endpoint_enforces_rbac ____________________
tests/unit/test_promotions_endpoint.py:155: in test_promotions_endpoint_enforces_rbac
    with patch("services.api.main.check_permission") as mock_check:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'check_permission'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
... (122 more lines truncated)
```

## 2026-03-17T22:19:24Z  File: tests/unit/test_runs_readiness_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py FFFFFF                        [100%]

=================================== FAILURES ===================================
_________________ test_readiness_endpoint_requires_valid_ulid __________________
tests/unit/test_runs_readiness_endpoint.py:28: in test_readiness_endpoint_requires_valid_ulid
    assert response.status_code in [400, 422], \
E   AssertionError: Invalid ULID must be rejected
E   assert 404 in [400, 422]
E    +  where 404 = <Response [404 Not Found]>.status_code
___________ test_readiness_endpoint_returns_404_for_nonexistent_run ____________
tests/unit/test_runs_readiness_endpoint.py:40: in test_readiness_endpoint_returns_404_for_nonexistent_run
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_readiness_report'
_____________ test_readiness_response_includes_grade_and_blockers ______________
tests/unit/test_runs_readiness_endpoint.py:63: in test_readiness_response_includes_grade_and_blockers
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_readiness_report'
_____________ test_readiness_blockers_include_owner_and_next_step ______________
tests/unit/test_runs_readiness_endpoint.py:96: in test_readiness_blockers_include_owner_and_next_step
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
... (149 more lines truncated)
```
    wrote: services/api/routes/runs.py
    wrote: services/api/main.py
    retry 1 for tests/unit/test_runs_readiness_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:10: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:11: in <module>
    from libs.contracts.readiness import ReadinessReport
libs/contracts/readiness.py:11: in <module>
    from libs.contracts.enums import ReadinessStatus
E   ImportError: cannot import name 'ReadinessStatus' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:10: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:11: in <module>
    from libs.contracts.readiness import ReadinessReport
libs/contracts/readiness.py:11: in <module>
    from libs.contracts.enums import ReadinessStatus
E   ImportError: cannot import name 'ReadinessStatus' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:10: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:11: in <module>
    from libs.contracts.readiness import ReadinessReport
libs/contracts/readiness.py:11: in <module>
    from libs.contracts.enums import ReadinessStatus
E   ImportError: cannot import name 'ReadinessStatus' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:10: in <module>
... (157 more lines truncated)
```
    wrote (retry 1): libs/contracts/enums.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:9: in <module>
    from libs.contracts.readiness import ReadinessReport
E   ImportError: cannot import name 'ReadinessReport' from 'libs.contracts.readiness' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/readiness.py)
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:9: in <module>
    from libs.contracts.readiness import ReadinessReport
E   ImportError: cannot import name 'ReadinessReport' from 'libs.contracts.readiness' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/readiness.py)
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:9: in <module>
    from libs.contracts.readiness import ReadinessReport
E   ImportError: cannot import name 'ReadinessReport' from 'libs.contracts.readiness' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/readiness.py)
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:9: in <module>
    from libs.contracts.readiness import ReadinessReport
E   ImportError: cannot import name 'ReadinessReport' from 'libs.contracts.readiness' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/readiness.py)
____________ ERROR at setup of test_readiness_endpoint_is_read_only ____________
tests/unit/test_runs_readiness_endpoint.py:15: in client
... (145 more lines truncated)
```
```
============================= test session starts ==============================
collected 139 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [  8%]
tests/integration/test_m0_backend_api_importability.py F.....            [ 12%]
tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [ 20%]
tests/unit/test_artifact_storage_interface.py ................           [ 31%]
tests/unit/test_m0_frontend_structure.py ..F....F                        [ 37%]
tests/unit/test_m0_project_structure.py ...............................F [ 60%]
.F......................                                                 [ 77%]
tests/unit/test_metadata_database_interface.py ............              [ 86%]
tests/unit/test_promotions_endpoint.py EEEEEEE                           [ 91%]
tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [ 95%]
tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:9: in <module>
    from libs.contracts.readiness import ReadinessReport
E   ImportError: cannot import name 'ReadinessReport' from 'libs.contracts.readiness' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/readiness.py)
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:9: in <module>
    from libs.contracts.readiness import ReadinessReport
E   ImportError: cannot import name 'ReadinessReport' from 'libs.contracts.readiness' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/readiness.py)
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:9: in <module>
    from libs.contracts.readiness import ReadinessReport
E   ImportError: cannot import name 'ReadinessReport' from 'libs.contracts.readiness' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/readiness.py)
... (460 more lines truncated)
```

## 2026-03-17T22:20:06Z  S4 M0 — round 3/3, 8 file(s)


## 2026-03-17T22:20:06Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes.runs import router as runs_router, get_readiness_report
services/api/routes/runs.py:9: in <module>
    from libs.contracts.readiness import ReadinessReport
E   ImportError: cannot import name 'ReadinessReport' from 'libs.contracts.readiness' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/readiness.py)
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            10      0   100%
... (106 more lines truncated)
```
    wrote: libs/contracts/enums.py
    wrote: libs/contracts/readiness.py
    retry 1 for tests/acceptance/test_m0_bootstrap.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/readiness'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
libs/contracts/health.py                            5      5     0%   2-9
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                     53     53     0%   5-80
libs/contracts/promotion.py                        19     19     0%   2-31
... (96 more lines truncated)
```
    wrote (retry 1): services/api/routes/health.py
    wrote (retry 1): libs/contracts/health.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/readiness'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
libs/contracts/health.py                            8      8     0%   2-18
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                     53     53     0%   5-80
libs/contracts/promotion.py                        19     19     0%   2-31
... (96 more lines truncated)
```

## 2026-03-17T22:20:26Z  File: tests/integration/test_m0_backend_api_importability.py

```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      6     0%   3-11
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
libs/contracts/health.py                            8      8     0%   2-18
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                     53     53     0%   5-80
... (97 more lines truncated)
```
    wrote: services/api/routes/health.py
    retry 1 for tests/integration/test_m0_backend_api_importability.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      6     0%   3-11
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
libs/contracts/health.py                            8      8     0%   2-18
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                     53     53     0%   5-80
... (97 more lines truncated)
```
    wrote (retry 1): services/api/routes/health.py
    wrote (retry 1): services/api/routes/strategies.py
    wrote (retry 1): services/api/routes/charts.py
    wrote (retry 1): services/api/routes/governance.py
    wrote (retry 1): services/api/routes/queues.py
    wrote (retry 1): services/api/routes/exports.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/__init__.py
    wrote (retry 1): services/api/__init__.py

## 2026-03-17T22:20:50Z  File: tests/unit/test_api_bootstrap.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py ..FFFFF.F.                              [100%]

=================================== FAILURES ===================================
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:60: in test_ac2_runs_results_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/results route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:76: in test_ac2_runs_readiness_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/readiness route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
_________________ test_ac2_promotions_request_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:98: in test_ac2_promotions_request_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: POST /promotions/request route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
__________________ test_ac2_approvals_approve_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:119: in test_ac2_approvals_approve_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: POST /approvals/{id}/approve route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
________________________ test_ac2_audit_endpoint_exists ________________________
tests/unit/test_api_bootstrap.py:134: in test_ac2_audit_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /audit route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
___________________ test_ac3_application_has_openapi_schema ____________________
tests/unit/test_api_bootstrap.py:170: in test_ac3_application_has_openapi_schema
    assert "/runs/{run_id}/results" in paths, \
E   AssertionError: Results endpoint must appear in OpenAPI schema
... (132 more lines truncated)
```
    wrote: services/api/main.py
    wrote: services/api/__init__.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/routes/approvals.py
    wrote: services/api/routes/audit.py

## 2026-03-17T22:21:10Z  File: tests/unit/test_m0_frontend_structure.py

```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py ..F....F                        [100%]

=================================== FAILURES ===================================
__________________ test_ac3_tsconfig_exists_with_strict_mode ___________________
tests/unit/test_m0_frontend_structure.py:61: in test_ac3_tsconfig_exists_with_strict_mode
    tsconfig_data = json.load(f)
                    ^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/json/__init__.py:293: in load
    return loads(fp.read(),
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/json/__init__.py:346: in loads
    return _default_decoder.decode(s)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/json/decoder.py:338: in decode
    obj, end = self.raw_decode(s, idx=_w(s, 0).end())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/json/decoder.py:354: in raw_decode
    obj, end = self.scan_once(s, idx)
               ^^^^^^^^^^^^^^^^^^^^^^
E   json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 10 column 5 (char 207)
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
... (122 more lines truncated)
```
    wrote: frontend/tsconfig.json
    wrote: frontend/tsconfig.node.json
    wrote: frontend/vite.config.ts
    wrote: frontend/index.html
    retry 1 for tests/unit/test_m0_frontend_structure.py
```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .......F                        [100%]

=================================== FAILURES ===================================
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      9     0%   2-18
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      6     0%   3-11
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
... (105 more lines truncated)
```
    wrote (retry 1): frontend/README.md
```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .......F                        [100%]

=================================== FAILURES ===================================
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      9     0%   2-18
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      6     0%   3-11
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
... (105 more lines truncated)
```

## 2026-03-17T22:21:47Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:5: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:4: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:8: in <module>
    from libs.contracts.enums import StrategyType
E   ImportError: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:5: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:5: in <module>
    from libs.contracts.research import ExperimentPlan, ExperimentRequest
libs/contracts/research.py:8: in <module>
    from libs.contracts.enums import ResearchPhase
E   ImportError: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
================================ tests coverage ================================
... (126 more lines truncated)
```
    wrote: libs/contracts/enums.py
    wrote: libs/experiment_plan/interfaces/__init__.py
    wrote: libs/experiment_plan/__init__.py
    wrote: libs/experiment_plan/mocks/__init__.py
    wrote: libs/strategy_compiler/__init__.py
    wrote: libs/strategy_compiler/interfaces/__init__.py
    wrote: libs/strategy_compiler/mocks/__init__.py
    retry 1 for tests/unit/test_m0_project_structure.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ................................ [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:4: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:6: in <module>
    from libs.contracts.research import ExperimentPlan, ExperimentResult
libs/contracts/research.py:8: in <module>
    from libs.contracts.enums import ResearchPhase
E   ImportError: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
... (109 more lines truncated)
```
    wrote (retry 1): libs/contracts/enums.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:4: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:6: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:8: in <module>
    from libs.contracts.enums import StrategyType
E   ImportError: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:4: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:6: in <module>
    from libs.contracts.research import ExperimentPlan, ExperimentResult
E   ImportError: cannot import name 'ExperimentResult' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ExperimentResult' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

... (124 more lines truncated)
```

## 2026-03-17T22:22:10Z  File: tests/unit/test_promotions_endpoint.py

```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py FFFFFFF                           [100%]

=================================== FAILURES ===================================
________________ test_promotions_endpoint_requires_candidate_id ________________
tests/unit/test_promotions_endpoint.py:32: in test_promotions_endpoint_requires_candidate_id
    assert response.status_code == 422, \
E   AssertionError: Request without candidate_id must be rejected
E   assert 200 == 422
E    +  where 200 = <Response [200 OK]>.status_code
---------------------------- Captured stdout setup -----------------------------
2026-03-17 18:22:11 [info     ] fastapi_app_initialized        title='FXLab API' version=0.1.0
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:22:11 [info     ] request_promotion_called       payload={'target_environment': 'paper', 'requester_id': '01HQ7X9Z8K3M4N5P6Q7R8S9T0W'}
_____________ test_promotions_endpoint_requires_target_environment _____________
tests/unit/test_promotions_endpoint.py:49: in test_promotions_endpoint_requires_target_environment
    assert response.status_code == 422, \
E   AssertionError: Request without target_environment must be rejected
E   assert 200 == 422
E    +  where 200 = <Response [200 OK]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:22:11 [info     ] request_promotion_called       payload={'candidate_id': '01HQ7X9Z8K3M4N5P6Q7R8S9T0V', 'requester_id': '01HQ7X9Z8K3M4N5P6Q7R8S9T0W'}
________________ test_promotions_endpoint_validates_ulid_format ________________
tests/unit/test_promotions_endpoint.py:67: in test_promotions_endpoint_validates_ulid_format
    assert response.status_code == 422, \
E   AssertionError: Invalid ULID format must be rejected
E   assert 200 == 422
E    +  where 200 = <Response [200 OK]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:22:11 [info     ] request_promotion_called       payload={'candidate_id': 'not-a-ulid', 'target_environment': 'paper', 'requester_id': 'also-not-a-ulid'}
_____________ test_promotions_endpoint_returns_job_id_immediately ______________
tests/unit/test_promotions_endpoint.py:88: in test_promotions_endpoint_returns_job_id_immediately
    with patch("services.api.main.submit_promotion_request") as mock_submit:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
... (162 more lines truncated)
```
    wrote: services/api/routes/promotions.py
    wrote: services/api/main.py
    wrote: libs/contracts/promotion.py
    wrote: services/api/__init__.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/main.py
    wrote: services/api/__init__.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/main.py
    retry 1 for tests/unit/test_promotions_endpoint.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py ....F.F                           [100%]

=================================== FAILURES ===================================
_________________ test_promotions_endpoint_creates_audit_event _________________
tests/unit/test_promotions_endpoint.py:114: in test_promotions_endpoint_creates_audit_event
    patch("services.api.main.audit_service") as mock_audit:
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'audit_service'
____________________ test_promotions_endpoint_enforces_rbac ____________________
tests/unit/test_promotions_endpoint.py:155: in test_promotions_endpoint_enforces_rbac
    with patch("services.api.main.check_permission") as mock_check:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'check_permission'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
... (113 more lines truncated)
```
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/promotions.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py ....FF.                           [100%]

=================================== FAILURES ===================================
_________________ test_promotions_endpoint_creates_audit_event _________________
tests/unit/test_promotions_endpoint.py:118: in test_promotions_endpoint_creates_audit_event
    response = client.post("/promotions/request", json=payload)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/starlette/testclient.py:546: in post
    return super().post(
.venv/lib/python3.12/site-packages/httpx/_client.py:1144: in post
    return self.request(
.venv/lib/python3.12/site-packages/starlette/testclient.py:445: in request
    return super().request(
.venv/lib/python3.12/site-packages/httpx/_client.py:825: in request
    return self.send(request, auth=auth, follow_redirects=follow_redirects)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/httpx/_client.py:914: in send
    response = self._send_handling_auth(
.venv/lib/python3.12/site-packages/httpx/_client.py:942: in _send_handling_auth
    response = self._send_handling_redirects(
.venv/lib/python3.12/site-packages/httpx/_client.py:979: in _send_handling_redirects
    response = self._send_single_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/httpx/_client.py:1014: in _send_single_request
    response = transport.handle_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/starlette/testclient.py:348: in handle_request
    raise exc
.venv/lib/python3.12/site-packages/starlette/testclient.py:345: in handle_request
    portal.call(self.app, scope, receive, send)
.venv/lib/python3.12/site-packages/anyio/from_thread.py:334: in call
    return cast(T_Retval, self.start_task_soon(func, *args).result())
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/concurrent/futures/_base.py:456: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/concurrent/futures/_base.py:401: in __get_result
... (184 more lines truncated)
```

## 2026-03-17T22:23:32Z  File: tests/unit/test_runs_readiness_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py FFFFFF                        [100%]

=================================== FAILURES ===================================
_________________ test_readiness_endpoint_requires_valid_ulid __________________
tests/unit/test_runs_readiness_endpoint.py:28: in test_readiness_endpoint_requires_valid_ulid
    assert response.status_code in [400, 422], \
E   AssertionError: Invalid ULID must be rejected
E   assert 404 in [400, 422]
E    +  where 404 = <Response [404 Not Found]>.status_code
___________ test_readiness_endpoint_returns_404_for_nonexistent_run ____________
tests/unit/test_runs_readiness_endpoint.py:40: in test_readiness_endpoint_returns_404_for_nonexistent_run
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_readiness_report'
_____________ test_readiness_response_includes_grade_and_blockers ______________
tests/unit/test_runs_readiness_endpoint.py:63: in test_readiness_response_includes_grade_and_blockers
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_readiness_report'
_____________ test_readiness_blockers_include_owner_and_next_step ______________
tests/unit/test_runs_readiness_endpoint.py:96: in test_readiness_blockers_include_owner_and_next_step
    with patch("services.api.main.get_readiness_report") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
... (149 more lines truncated)
```
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/readiness.py
    wrote: libs/contracts/readiness.py
    wrote: libs/contracts/base.py
    retry 1 for tests/unit/test_runs_readiness_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py ..FF.F                        [100%]

=================================== FAILURES ===================================
_____________ test_readiness_response_includes_grade_and_blockers ______________
tests/unit/test_runs_readiness_endpoint.py:66: in test_readiness_response_includes_grade_and_blockers
    response = client.get(f"/runs/{test_run_id}/readiness")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/starlette/testclient.py:473: in get
    return super().get(
.venv/lib/python3.12/site-packages/httpx/_client.py:1053: in get
    return self.request(
.venv/lib/python3.12/site-packages/starlette/testclient.py:445: in request
    return super().request(
.venv/lib/python3.12/site-packages/httpx/_client.py:825: in request
    return self.send(request, auth=auth, follow_redirects=follow_redirects)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/httpx/_client.py:914: in send
    response = self._send_handling_auth(
.venv/lib/python3.12/site-packages/httpx/_client.py:942: in _send_handling_auth
    response = self._send_handling_redirects(
.venv/lib/python3.12/site-packages/httpx/_client.py:979: in _send_handling_redirects
    response = self._send_single_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/httpx/_client.py:1014: in _send_single_request
    response = transport.handle_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.12/site-packages/starlette/testclient.py:348: in handle_request
    raise exc
.venv/lib/python3.12/site-packages/starlette/testclient.py:345: in handle_request
    portal.call(self.app, scope, receive, send)
.venv/lib/python3.12/site-packages/anyio/from_thread.py:334: in call
    return cast(T_Retval, self.start_task_soon(func, *args).result())
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/concurrent/futures/_base.py:456: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/concurrent/futures/_base.py:401: in __get_result
... (340 more lines truncated)
```
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py ..FF.F                        [100%]

=================================== FAILURES ===================================
_____________ test_readiness_response_includes_grade_and_blockers ______________
tests/unit/test_runs_readiness_endpoint.py:69: in test_readiness_response_includes_grade_and_blockers
    assert "readiness_grade" in data, \
E   AssertionError: Response must include readiness_grade
E   assert 'readiness_grade' in {'detail': 'Run not found'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:24:25 [info     ] get_run_readiness_called       run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:25 [info     ] get_readiness_report_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:25 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
_____________ test_readiness_blockers_include_owner_and_next_step ______________
tests/unit/test_runs_readiness_endpoint.py:102: in test_readiness_blockers_include_owner_and_next_step
    blockers = data["blockers"]
               ^^^^^^^^^^^^^^^^
E   KeyError: 'blockers'
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:24:25 [info     ] get_run_readiness_called       run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:25 [info     ] get_readiness_report_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:25 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
_______________ test_readiness_report_includes_scoring_evidence ________________
tests/unit/test_runs_readiness_endpoint.py:155: in test_readiness_report_includes_scoring_evidence
    assert "scoring_evidence" in data, \
E   AssertionError: Readiness report must include scoring evidence
E   assert 'scoring_evidence' in {'detail': 'Run not found'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:24:25 [info     ] get_run_readiness_called       run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:25 [info     ] get_readiness_report_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:25 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
... (121 more lines truncated)
```

## 2026-03-17T22:24:25Z  File: tests/unit/test_runs_results_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py FFFFFF                          [100%]

=================================== FAILURES ===================================
_______________ test_results_endpoint_requires_valid_ulid_format _______________
tests/unit/test_runs_results_endpoint.py:29: in test_results_endpoint_requires_valid_ulid_format
    assert response.status_code in [400, 422], \
E   AssertionError: Invalid ULID format must be rejected with 400 or 422
E   assert 404 in [400, 422]
E    +  where 404 = <Response [404 Not Found]>.status_code
---------------------------- Captured stdout setup -----------------------------
2026-03-17 18:24:26 [info     ] fastapi_app_initialized
____________ test_results_endpoint_returns_404_for_nonexistent_run _____________
tests/unit/test_runs_results_endpoint.py:42: in test_results_endpoint_returns_404_for_nonexistent_run
    with patch("services.api.main.get_run_results") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_run_results'
________________ test_results_endpoint_returns_structured_json _________________
tests/unit/test_runs_results_endpoint.py:66: in test_results_endpoint_returns_structured_json
    with patch("services.api.main.get_run_results") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
                      ^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1437: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/Users/gjohnson/Documents/Coding Projects/fxlab/services/api/main.py'> does not have the attribute 'get_run_results'
________________ test_results_endpoint_includes_metadata_fields ________________
tests/unit/test_runs_results_endpoint.py:95: in test_results_endpoint_includes_metadata_fields
    with patch("services.api.main.get_run_results") as mock_get:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:1467: in __enter__
    original, local = self.get_original()
... (155 more lines truncated)
```
    wrote: services/api/routes/runs.py
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    retry 1 for tests/unit/test_runs_results_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py ..FFF.                          [100%]

=================================== FAILURES ===================================
________________ test_results_endpoint_returns_structured_json _________________
tests/unit/test_runs_results_endpoint.py:72: in test_results_endpoint_returns_structured_json
    assert response.status_code == 200, \
E   AssertionError: Valid run must return 200 OK
E   assert 404 == 200
E    +  where 404 = <Response [404 Not Found]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:24:45 [info     ] get_results_endpoint_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:45 [info     ] get_run_results_called         run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:45 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
________________ test_results_endpoint_includes_metadata_fields ________________
tests/unit/test_runs_results_endpoint.py:101: in test_results_endpoint_includes_metadata_fields
    assert "completed_at" in data, "Results must include completion timestamp"
E   AssertionError: Results must include completion timestamp
E   assert 'completed_at' in {'detail': 'Run not found: 01HQ7X9Z8K3M4N5P6Q7R8S9T0V'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:24:45 [info     ] get_results_endpoint_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:45 [info     ] get_run_results_called         run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:45 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
___________ test_results_endpoint_handles_service_errors_gracefully ____________
tests/unit/test_runs_results_endpoint.py:118: in test_results_endpoint_handles_service_errors_gracefully
    assert response.status_code == 500, \
E   AssertionError: Service errors must return 500 Internal Server Error
E   assert 404 == 500
E    +  where 404 = <Response [404 Not Found]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:24:45 [info     ] get_results_endpoint_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:45 [info     ] get_run_results_called         run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:24:45 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
... (123 more lines truncated)
```
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py ..FFF.                          [100%]

=================================== FAILURES ===================================
________________ test_results_endpoint_returns_structured_json _________________
tests/unit/test_runs_results_endpoint.py:72: in test_results_endpoint_returns_structured_json
    assert response.status_code == 200, \
E   AssertionError: Valid run must return 200 OK
E   assert 404 == 200
E    +  where 404 = <Response [404 Not Found]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:25:03 [info     ] get_results_endpoint_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:25:03 [info     ] get_run_results_called         run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:25:03 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
________________ test_results_endpoint_includes_metadata_fields ________________
tests/unit/test_runs_results_endpoint.py:101: in test_results_endpoint_includes_metadata_fields
    assert "completed_at" in data, "Results must include completion timestamp"
E   AssertionError: Results must include completion timestamp
E   assert 'completed_at' in {'detail': 'Run not found: 01HQ7X9Z8K3M4N5P6Q7R8S9T0V'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:25:03 [info     ] get_results_endpoint_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:25:03 [info     ] get_run_results_called         run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:25:03 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
___________ test_results_endpoint_handles_service_errors_gracefully ____________
tests/unit/test_runs_results_endpoint.py:118: in test_results_endpoint_handles_service_errors_gracefully
    assert response.status_code == 500, \
E   AssertionError: Service errors must return 500 Internal Server Error
E   assert 404 == 500
E    +  where 404 = <Response [404 Not Found]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:25:03 [info     ] get_results_endpoint_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:25:03 [info     ] get_run_results_called         run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
2026-03-17 18:25:03 [warning  ] run_not_found                  run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
=============================== warnings summary ===============================
tests/unit/test_runs_results_endpoint.py::test_results_endpoint_requires_valid_ulid_format
  /Users/gjohnson/Documents/Coding Projects/fxlab/.venv/lib/python3.12/site-packages/fastapi/routing.py:324: DeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.
    return await dependant.call(**values)

... (129 more lines truncated)
```
```
============================= test session starts ==============================
collected 139 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [  8%]
tests/integration/test_m0_backend_api_importability.py F.....            [ 12%]
tests/unit/test_api_bootstrap.py ..FFFFF.F.                              [ 20%]
tests/unit/test_artifact_storage_interface.py ................           [ 31%]
tests/unit/test_m0_frontend_structure.py .......F                        [ 37%]
tests/unit/test_m0_project_structure.py ...............................F [ 60%]
.F......................                                                 [ 77%]
tests/unit/test_metadata_database_interface.py ............              [ 86%]
tests/unit/test_promotions_endpoint.py FFFFFFF                           [ 91%]
tests/unit/test_runs_readiness_endpoint.py FFFFFF                        [ 95%]
tests/unit/test_runs_results_endpoint.py ..FFF.                          [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/results'}
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:25:04 [info     ] fastapi_app_initialized
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:60: in test_ac2_runs_results_endpoint_exists
    assert response.status_code != 404, \
E   AssertionError: GET /runs/{run_id}/results route must be registered
E   assert 404 != 404
E    +  where 404 = <Response [404 Not Found]>.status_code
----------------------------- Captured stdout call -----------------------------
2026-03-17 18:25:04 [info     ] get_results_endpoint_called    run_id=01HQ7X9Z8K3M4N5P6Q7R8S9T0V
... (366 more lines truncated)
```

## 2026-03-18T20:41:01Z  S4 M0 — round 1/3, 8 file(s)


## 2026-03-18T20:41:01Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/results'}
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:41:02 [info     ] fastapi_app_initialized
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            11      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           39     39     0%   7-92
... (104 more lines truncated)
```
    wrote: libs/contracts/enums.py
    wrote: services/api/routes/health.py
    wrote: services/api/main.py
    retry 1 for tests/acceptance/test_m0_bootstrap.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:41:15 [info     ] fastapi_app_initialized
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            20      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
... (101 more lines truncated)
```
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:41:30 [info     ] fastapi_app_initialized
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      0   100%
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            20      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
... (101 more lines truncated)
```

## 2026-03-18T20:41:32Z  File: tests/integration/test_m0_backend_api_importability.py

```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:41:33 [info     ] fastapi_app_initialized
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      9     0%   6-31
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            20     20     0%   5-35
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
... (101 more lines truncated)
```
    wrote: services/api/main.py
    wrote: services/api/routes/strategies.py
    wrote: services/api/routes/charts.py
    wrote: services/api/routes/governance.py
    wrote: services/api/routes/queues.py
    retry 1 for tests/integration/test_m0_backend_api_importability.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:41:50 [info     ] fastapi_app_initialized
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      9     0%   6-31
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            20     20     0%   5-35
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
... (101 more lines truncated)
```
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/strategies.py
    wrote (retry 1): services/api/routes/charts.py
    wrote (retry 1): services/api/routes/governance.py
    wrote (retry 1): services/api/routes/queues.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:06 [info     ] fastapi_app_initialized
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      9     0%   6-31
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            20     20     0%   5-35
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
libs/contracts/feed_health.py                      40     40     0%   7-87
libs/contracts/governance.py                       40     40     0%   5-64
... (101 more lines truncated)
```

## 2026-03-18T20:42:07Z  File: tests/unit/test_api_bootstrap.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:08 [info     ] fastapi_app_initialized
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:08 [info     ] fastapi_app_initialized
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:08 [info     ] fastapi_app_initialized
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:70: in test_ac2_runs_readiness_endpoint_exists
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
... (191 more lines truncated)
```
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/routes/approvals.py
    wrote: services/api/routes/audit.py
    wrote: services/api/__init__.py
    retry 1 for tests/unit/test_api_bootstrap.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:33 [info     ] fastapi_app_initialized
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:33 [info     ] fastapi_app_initialized
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:33 [info     ] fastapi_app_initialized
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:70: in test_ac2_runs_readiness_endpoint_exists
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
... (191 more lines truncated)
```
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/routes/approvals.py
    wrote (retry 1): services/api/routes/audit.py
    wrote (retry 1): services/api/__init__.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:55 [info     ] fastapi_app_initialized
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:55 [info     ] fastapi_app_initialized
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
----------------------------- Captured stdout call -----------------------------
2026-03-18 16:42:55 [info     ] fastapi_app_initialized
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:70: in test_ac2_runs_readiness_endpoint_exists
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
... (191 more lines truncated)
```

## 2026-03-18T20:42:56Z  File: tests/unit/test_m0_frontend_structure.py

```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .......F                        [100%]

=================================== FAILURES ===================================
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                              9      9     0%   6-31
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            20     20     0%   5-35
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
... (105 more lines truncated)
```
    ENV_SKIP — missing: npm/node (frontend toolchain binary not installed)

## 2026-03-18T20:42:58Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:4: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:6: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:8: in <module>
    from libs.contracts.enums import StrategyType
E   ImportError: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:4: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:6: in <module>
    from libs.contracts.research import ExperimentPlan, ExperimentResult
E   ImportError: cannot import name 'ExperimentResult' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ExperimentResult' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

... (124 more lines truncated)
```
    wrote: libs/contracts/enums.py
    wrote: libs/experiment_plan/interfaces/__init__.py

## 2026-03-18T20:43:09Z  File: tests/unit/test_promotions_endpoint.py

```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
---------------------------- Captured stdout setup -----------------------------
2026-03-18 16:43:10 [info     ] fastapi_app_initialized
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
---------------------------- Captured stdout setup -----------------------------
2026-03-18 16:43:10 [info     ] fastapi_app_initialized
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
---------------------------- Captured stdout setup -----------------------------
2026-03-18 16:43:10 [info     ] fastapi_app_initialized
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:34: in <module>
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                                        ^^^^^^^^^^^^^
E   NameError: name 'AsyncIterator' is not defined
... (161 more lines truncated)
```
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/promotions.py
    wrote: libs/contracts/promotion.py
    wrote: libs/contracts/enums.py
    wrote: libs/contracts/base.py
    wrote: services/__init__.py
    wrote: services/api/__init__.py
    retry 1 for tests/unit/test_promotions_endpoint.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
... (175 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
... (175 more lines truncated)
```

## 2026-03-18T20:44:10Z  File: tests/unit/test_runs_readiness_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
... (163 more lines truncated)
```
    wrote: libs/contracts/base.py
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    retry 1 for tests/unit/test_runs_readiness_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
... (163 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/__init__.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:9: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:9: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:9: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
... (163 more lines truncated)
```

## 2026-03-18T20:44:51Z  File: tests/unit/test_runs_results_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:9: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:9: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:9: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
... (163 more lines truncated)
```
    wrote: libs/contracts/base.py
    wrote: services/api/routes/runs.py
    wrote: services/api/main.py
    retry 1 for tests/unit/test_runs_results_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
... (163 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/runs.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
... (163 more lines truncated)
```
```
============================= test session starts ==============================
collected 139 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [  8%]
tests/integration/test_m0_backend_api_importability.py F.....            [ 12%]
tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [ 20%]
tests/unit/test_artifact_storage_interface.py ................           [ 31%]
tests/unit/test_m0_frontend_structure.py .......F                        [ 37%]
tests/unit/test_m0_project_structure.py ...............................F [ 60%]
.F......................                                                 [ 77%]
tests/unit/test_metadata_database_interface.py ............              [ 86%]
tests/unit/test_promotions_endpoint.py EEEEEEE                           [ 91%]
tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [ 95%]
tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
... (525 more lines truncated)
```

## 2026-03-18T20:45:39Z  S4 M0 — round 2/3, 8 file(s)


## 2026-03-18T20:45:39Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:169: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (112 more lines truncated)
```
    wrote: libs/contracts/base.py
    retry 1 for tests/acceptance/test_m0_bootstrap.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:169: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (112 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:169: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (112 more lines truncated)
```

## 2026-03-18T20:46:00Z  File: tests/integration/test_m0_backend_api_importability.py

```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             16      6    62%   37-46
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            64     64     0%   5-99
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
... (103 more lines truncated)
```
    wrote: libs/contracts/base.py
    retry 1 for tests/integration/test_m0_backend_api_importability.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             20     10    50%   37-55
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            64     64     0%   5-99
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
... (103 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             27     17    37%   37-67
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            64     64     0%   5-99
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
... (103 more lines truncated)
```

## 2026-03-18T20:46:24Z  File: tests/unit/test_api_bootstrap.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
... (211 more lines truncated)
```
    wrote: libs/contracts/base.py
    wrote: services/api/__init__.py
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/routes/approvals.py
    wrote: services/api/routes/audit.py
    retry 1 for tests/unit/test_api_bootstrap.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:7: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:7: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:7: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
... (211 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/routes/approvals.py
    wrote (retry 1): services/api/routes/audit.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
... (211 more lines truncated)
```

## 2026-03-18T20:47:19Z  File: tests/unit/test_m0_frontend_structure.py

```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .......F                        [100%]

=================================== FAILURES ===================================
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:145: in test_ac8_npm_build_succeeds
    result = subprocess.run(
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'npm'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             27     27     0%   6-67
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            64     64     0%   5-99
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           39     39     0%   7-92
... (105 more lines truncated)
```
    ENV_SKIP — missing: npm/node (frontend toolchain binary not installed)

## 2026-03-18T20:47:20Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:4: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:6: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:7: in <module>
    from libs.contracts.base import FXLabBaseModel
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:4: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:7: in <module>
    from libs.contracts.research import ExperimentPlan
libs/contracts/research.py:7: in <module>
    from libs.contracts.base import FXLabBaseModel
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
... (122 more lines truncated)
```
    wrote: libs/contracts/base.py
    retry 1 for tests/unit/test_m0_project_structure.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:4: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:6: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:7: in <module>
    from libs.contracts.base import FXLabBaseModel
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:4: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:7: in <module>
    from libs.contracts.research import ExperimentPlan
libs/contracts/research.py:7: in <module>
    from libs.contracts.base import FXLabBaseModel
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
... (122 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F......................                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:4: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:6: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:7: in <module>
    from libs.contracts.base import FXLabBaseModel
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:4: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:7: in <module>
    from libs.contracts.research import ExperimentPlan
libs/contracts/research.py:7: in <module>
    from libs.contracts.base import FXLabBaseModel
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
... (122 more lines truncated)
```

## 2026-03-18T20:47:49Z  File: tests/unit/test_promotions_endpoint.py

```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
... (175 more lines truncated)
```
    wrote: libs/contracts/base.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/main.py
    retry 1 for tests/unit/test_promotions_endpoint.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import ULID_PATTERN, APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
... (175 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
    wrote (retry 1): libs/contracts/promotion.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/dependencies.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): libs/contracts/enums.py
    wrote (retry 1): services/__init__.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/routes/__init__.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'services.api.routes.runs' has no attribute 'get_run_results'
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'services.api.routes.runs' has no attribute 'get_run_results'
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'services.api.routes.runs' has no attribute 'get_run_results'
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'services.api.routes.runs' has no attribute 'get_run_results'
________ ERROR at setup of test_promotions_endpoint_creates_audit_event ________
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
... (147 more lines truncated)
```

## 2026-03-18T20:49:16Z  File: tests/unit/test_runs_readiness_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'services.api.routes.runs' has no attribute 'get_run_results'
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'services.api.routes.runs' has no attribute 'get_run_results'
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'services.api.routes.runs' has no attribute 'get_run_results'
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'services.api.routes.runs' has no attribute 'get_run_results'
____________ ERROR at setup of test_readiness_endpoint_is_read_only ____________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    get_run_results = runs.get_run_results
                      ^^^^^^^^^^^^^^^^^^^^
... (139 more lines truncated)
```
    wrote: services/api/routes/runs.py
    wrote: services/api/main.py
    retry 1 for tests/unit/test_runs_readiness_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:8: in <module>
    from libs.contracts.base import APIResponse
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
... (163 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): libs/contracts/readiness.py
    wrote (retry 1): libs/contracts/enums.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/__init__.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
... (163 more lines truncated)
```

## 2026-03-18T20:50:29Z  File: tests/unit/test_runs_results_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:6: in <module>
    from libs.contracts.base import APIResponse, ULID_PATTERN
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
... (163 more lines truncated)
```
    wrote: libs/contracts/base.py
    wrote: services/api/routes/runs.py
    wrote: services/api/main.py
    wrote: services/api/main.py
    wrote: services/api/routes/runs.py
    retry 1 for tests/unit/test_runs_results_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import is_valid_ulid
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import is_valid_ulid
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import is_valid_ulid
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
... (163 more lines truncated)
```
    wrote (retry 1): libs/contracts/base.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/__init__.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import is_valid_ulid
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import is_valid_ulid
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import is_valid_ulid
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
... (163 more lines truncated)
```
```
============================= test session starts ==============================
collected 139 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [  8%]
tests/integration/test_m0_backend_api_importability.py F.....            [ 12%]
tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [ 20%]
tests/unit/test_artifact_storage_interface.py ................           [ 31%]
tests/unit/test_m0_frontend_structure.py .......F                        [ 37%]
tests/unit/test_m0_project_structure.py ...............................F [ 60%]
.F......................                                                 [ 77%]
tests/unit/test_metadata_database_interface.py ............              [ 86%]
tests/unit/test_promotions_endpoint.py EEEEEEE                           [ 91%]
tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [ 95%]
tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import is_valid_ulid
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:8: in <module>
    from services.api.routes import runs
services/api/routes/runs.py:10: in <module>
    from libs.contracts.base import is_valid_ulid
libs/contracts/base.py:34: in <module>
    ULID_PATTERN = re.compile(r'^[0-7][0-9A-HJKMNP-TV-Z]{25}$')
                   ^^
E   NameError: name 're' is not defined. Did you forget to import 're'
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
... (525 more lines truncated)
```
    OSCILLATION: fingerprint ['tests/acceptance/test_m0_bootstrap.py', 'tests/integration/test_m0_backend_api_importability.py', 'tests/unit/test_api_bootstrap.py', 'tests/unit/test_m0_project_structure.py', 'tests/unit/test_promotions_endpoint.py', 'tests/unit/test_runs_readiness_endpoint.py', 'tests/unit/test_runs_results_endpoint.py'] seen at round 2 and again at round 3

## 2026-03-19T20:05:42Z  S4 M0 — round 1/3, 7 file(s)


## 2026-03-19T20:05:42Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/results'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:05:44 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

tests/acceptance/test_m0_bootstrap.py::test_api_health_route_importable
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             42     11    74%   44-46, 56, 60, 83, 87-91
... (108 more lines truncated)
```
    ENV_SKIP — missing: docker (container runtime not available)

## 2026-03-19T20:06:38Z  S4 M0 — round 1/3, 7 file(s)


## 2026-03-19T20:06:38Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/results'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:06:40 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

tests/acceptance/test_m0_bootstrap.py::test_api_health_route_importable
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             42     11    74%   44-46, 56, 60, 83, 87-91
... (108 more lines truncated)
```
    ENV_SKIP — missing: docker (container runtime not available)

## 2026-03-19T20:06:48Z  File: tests/integration/test_m0_backend_api_importability.py

```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:06:50 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (109 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/routes/health.py
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/strategies.py
    wrote: services/api/routes/charts.py
    wrote: services/api/routes/governance.py
    wrote: services/api/routes/queues.py
    wrote: services/api/routes/artifacts.py
    wrote: services/__init__.py
    wrote: services/api/__init__.py
    retry 1 for tests/integration/test_m0_backend_api_importability.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:07:21 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (110 more lines truncated)
```
    wrote (retry 1): services/api/routes/health.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:07:36 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (110 more lines truncated)
```

## 2026-03-19T20:07:44Z  File: tests/unit/test_api_bootstrap.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py ..FFFFF.FF                              [100%]

=================================== FAILURES ===================================
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:58: in test_ac2_runs_results_endpoint_exists
    response = client.get(f"/runs/{test_run_id}/results")
.venv/lib/python3.10/site-packages/starlette/testclient.py:473: in get
    return super().get(
.venv/lib/python3.10/site-packages/httpx/_client.py:1053: in get
    return self.request(
.venv/lib/python3.10/site-packages/starlette/testclient.py:445: in request
    return super().request(
.venv/lib/python3.10/site-packages/httpx/_client.py:825: in request
    return self.send(request, auth=auth, follow_redirects=follow_redirects)
.venv/lib/python3.10/site-packages/httpx/_client.py:914: in send
    response = self._send_handling_auth(
.venv/lib/python3.10/site-packages/httpx/_client.py:942: in _send_handling_auth
    response = self._send_handling_redirects(
.venv/lib/python3.10/site-packages/httpx/_client.py:979: in _send_handling_redirects
    response = self._send_single_request(request)
.venv/lib/python3.10/site-packages/httpx/_client.py:1014: in _send_single_request
    response = transport.handle_request(request)
.venv/lib/python3.10/site-packages/starlette/testclient.py:348: in handle_request
    raise exc
.venv/lib/python3.10/site-packages/starlette/testclient.py:345: in handle_request
    portal.call(self.app, scope, receive, send)
.venv/lib/python3.10/site-packages/anyio/from_thread.py:334: in call
    return cast(T_Retval, self.start_task_soon(func, *args).result())
/usr/lib/python3.10/concurrent/futures/_base.py:458: in result
    return self.__get_result()
/usr/lib/python3.10/concurrent/futures/_base.py:403: in __get_result
    raise self._exception
.venv/lib/python3.10/site-packages/anyio/from_thread.py:259: in _call_func
    retval = await retval_or_awaitable
.venv/lib/python3.10/site-packages/fastapi/applications.py:1160: in __call__
    await super().__call__(scope, receive, send)
.venv/lib/python3.10/site-packages/starlette/applications.py:107: in __call__
... (299 more lines truncated)
```

## 2026-03-19T20:08:48Z  S4 M0 — round 1/3, 7 file(s)


## 2026-03-19T20:08:48Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc', '/runs/{run_id}/results'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:08:50 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

tests/acceptance/test_m0_bootstrap.py::test_api_health_route_importable
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             42     11    74%   44-46, 56, 60, 83, 87-91
... (109 more lines truncated)
```
    ENV_SKIP — missing: docker (container runtime not available)

## 2026-03-19T20:08:58Z  File: tests/integration/test_m0_backend_api_importability.py

```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:08:59 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (110 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/routes/health.py
    retry 1 for tests/integration/test_m0_backend_api_importability.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:09:26 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (110 more lines truncated)
```
    wrote (retry 1): services/api/routes/health.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:24: in test_ac9_phase1_health_endpoint_returns_success
    assert "success" in data, "Health response missing 'success' field"
E   AssertionError: Health response missing 'success' field
E   assert 'success' in {'status': 'healthy'}
----------------------------- Captured stdout call -----------------------------
2026-03-19 16:09:41 [info     ] fastapi_app_initialized
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (110 more lines truncated)
```

## 2026-03-19T20:09:50Z  File: tests/unit/test_api_bootstrap.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py ..FFFFF.FF                              [100%]

=================================== FAILURES ===================================
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:58: in test_ac2_runs_results_endpoint_exists
    response = client.get(f"/runs/{test_run_id}/results")
.venv/lib/python3.10/site-packages/starlette/testclient.py:473: in get
    return super().get(
.venv/lib/python3.10/site-packages/httpx/_client.py:1053: in get
    return self.request(
.venv/lib/python3.10/site-packages/starlette/testclient.py:445: in request
    return super().request(
.venv/lib/python3.10/site-packages/httpx/_client.py:825: in request
    return self.send(request, auth=auth, follow_redirects=follow_redirects)
.venv/lib/python3.10/site-packages/httpx/_client.py:914: in send
    response = self._send_handling_auth(
.venv/lib/python3.10/site-packages/httpx/_client.py:942: in _send_handling_auth
    response = self._send_handling_redirects(
.venv/lib/python3.10/site-packages/httpx/_client.py:979: in _send_handling_redirects
    response = self._send_single_request(request)
.venv/lib/python3.10/site-packages/httpx/_client.py:1014: in _send_single_request
    response = transport.handle_request(request)
.venv/lib/python3.10/site-packages/starlette/testclient.py:348: in handle_request
    raise exc
.venv/lib/python3.10/site-packages/starlette/testclient.py:345: in handle_request
    portal.call(self.app, scope, receive, send)
.venv/lib/python3.10/site-packages/anyio/from_thread.py:334: in call
    return cast(T_Retval, self.start_task_soon(func, *args).result())
/usr/lib/python3.10/concurrent/futures/_base.py:458: in result
    return self.__get_result()
/usr/lib/python3.10/concurrent/futures/_base.py:403: in __get_result
    raise self._exception
.venv/lib/python3.10/site-packages/anyio/from_thread.py:259: in _call_func
    retval = await retval_or_awaitable
.venv/lib/python3.10/site-packages/fastapi/applications.py:1160: in __call__
    await super().__call__(scope, receive, send)
.venv/lib/python3.10/site-packages/starlette/applications.py:107: in __call__
... (299 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/__init__.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/routes/approvals.py
    wrote: services/api/routes/audit.py
    wrote: services/api/main.py
    wrote: services/__init__.py
    retry 1 for tests/unit/test_api_bootstrap.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py ..FFFFF.FF                              [100%]

=================================== FAILURES ===================================
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:58: in test_ac2_runs_results_endpoint_exists
    response = client.get(f"/runs/{test_run_id}/results")
.venv/lib/python3.10/site-packages/starlette/testclient.py:473: in get
    return super().get(
.venv/lib/python3.10/site-packages/httpx/_client.py:1053: in get
    return self.request(
.venv/lib/python3.10/site-packages/starlette/testclient.py:445: in request
    return super().request(
.venv/lib/python3.10/site-packages/httpx/_client.py:825: in request
    return self.send(request, auth=auth, follow_redirects=follow_redirects)
.venv/lib/python3.10/site-packages/httpx/_client.py:914: in send
    response = self._send_handling_auth(
.venv/lib/python3.10/site-packages/httpx/_client.py:942: in _send_handling_auth
    response = self._send_handling_redirects(
.venv/lib/python3.10/site-packages/httpx/_client.py:979: in _send_handling_redirects
    response = self._send_single_request(request)
.venv/lib/python3.10/site-packages/httpx/_client.py:1014: in _send_single_request
    response = transport.handle_request(request)
.venv/lib/python3.10/site-packages/starlette/testclient.py:348: in handle_request
    raise exc
.venv/lib/python3.10/site-packages/starlette/testclient.py:345: in handle_request
    portal.call(self.app, scope, receive, send)
.venv/lib/python3.10/site-packages/anyio/from_thread.py:334: in call
    return cast(T_Retval, self.start_task_soon(func, *args).result())
/usr/lib/python3.10/concurrent/futures/_base.py:458: in result
    return self.__get_result()
/usr/lib/python3.10/concurrent/futures/_base.py:403: in __get_result
    raise self._exception
.venv/lib/python3.10/site-packages/anyio/from_thread.py:259: in _call_func
    retval = await retval_or_awaitable
.venv/lib/python3.10/site-packages/fastapi/applications.py:1160: in __call__
    await super().__call__(scope, receive, send)
.venv/lib/python3.10/site-packages/starlette/applications.py:107: in __call__
... (367 more lines truncated)
```
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/routes/approvals.py
    wrote (retry 1): services/api/routes/audit.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py ..FFFFF.FF                              [100%]

=================================== FAILURES ===================================
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:58: in test_ac2_runs_results_endpoint_exists
    response = client.get(f"/runs/{test_run_id}/results")
.venv/lib/python3.10/site-packages/starlette/testclient.py:473: in get
    return super().get(
.venv/lib/python3.10/site-packages/httpx/_client.py:1053: in get
    return self.request(
.venv/lib/python3.10/site-packages/starlette/testclient.py:445: in request
    return super().request(
.venv/lib/python3.10/site-packages/httpx/_client.py:825: in request
    return self.send(request, auth=auth, follow_redirects=follow_redirects)
.venv/lib/python3.10/site-packages/httpx/_client.py:914: in send
    response = self._send_handling_auth(
.venv/lib/python3.10/site-packages/httpx/_client.py:942: in _send_handling_auth
    response = self._send_handling_redirects(
.venv/lib/python3.10/site-packages/httpx/_client.py:979: in _send_handling_redirects
    response = self._send_single_request(request)
.venv/lib/python3.10/site-packages/httpx/_client.py:1014: in _send_single_request
    response = transport.handle_request(request)
.venv/lib/python3.10/site-packages/starlette/testclient.py:348: in handle_request
    raise exc
.venv/lib/python3.10/site-packages/starlette/testclient.py:345: in handle_request
    portal.call(self.app, scope, receive, send)
.venv/lib/python3.10/site-packages/anyio/from_thread.py:334: in call
    return cast(T_Retval, self.start_task_soon(func, *args).result())
/usr/lib/python3.10/concurrent/futures/_base.py:458: in result
    return self.__get_result()
/usr/lib/python3.10/concurrent/futures/_base.py:403: in __get_result
    raise self._exception
.venv/lib/python3.10/site-packages/anyio/from_thread.py:259: in _call_func
    retval = await retval_or_awaitable
.venv/lib/python3.10/site-packages/fastapi/applications.py:1160: in __call__
    await super().__call__(scope, receive, send)
.venv/lib/python3.10/site-packages/starlette/applications.py:107: in __call__
... (405 more lines truncated)
```

## 2026-03-19T20:11:09Z  File: tests/unit/test_m0_frontend_structure.py

```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .......F                        [100%]

=================================== FAILURES ===================================
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:152: in test_ac8_npm_build_succeeds
    assert result.returncode == 0, f"npm run build failed with exit code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
E   AssertionError: npm run build failed with exit code 127
E     stdout: 
E     > fxlab-frontend@0.0.0 build
E     > tsc && vite build
E     
E     
E     stderr: sh: 1: tsc: not found
E     
E   assert 127 == 0
E    +  where 127 = CompletedProcess(args=['npm', 'run', 'build'], returncode=127, stdout='\n> fxlab-frontend@0.0.0 build\n> tsc && vite build\n\n', stderr='sh: 1: tsc: not found\n').returncode
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (112 more lines truncated)
```
    ENV_SKIP — missing: npm build environment (node_modules not installed — run 'npm install' in the project root first)

## 2026-03-19T20:11:18Z  File: tests/unit/test_promotions_endpoint.py

```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py FFFFFFF                           [100%]

=================================== FAILURES ===================================
________________ test_promotions_endpoint_requires_candidate_id ________________
tests/unit/test_promotions_endpoint.py:32: in test_promotions_endpoint_requires_candidate_id
    assert response.status_code == 422, \
E   AssertionError: Request without candidate_id must be rejected
E   assert 404 == 422
E    +  where 404 = <Response [404 Not Found]>.status_code
---------------------------- Captured stdout setup -----------------------------
2026-03-19 16:11:20 [info     ] fastapi_app_initialized
_____________ test_promotions_endpoint_requires_target_environment _____________
tests/unit/test_promotions_endpoint.py:49: in test_promotions_endpoint_requires_target_environment
    assert response.status_code == 422, \
E   AssertionError: Request without target_environment must be rejected
E   assert 404 == 422
E    +  where 404 = <Response [404 Not Found]>.status_code
________________ test_promotions_endpoint_validates_ulid_format ________________
tests/unit/test_promotions_endpoint.py:67: in test_promotions_endpoint_validates_ulid_format
    assert response.status_code == 422, \
E   AssertionError: Invalid ULID format must be rejected
E   assert 404 == 422
E    +  where 404 = <Response [404 Not Found]>.status_code
_____________ test_promotions_endpoint_returns_job_id_immediately ______________
tests/unit/test_promotions_endpoint.py:93: in test_promotions_endpoint_returns_job_id_immediately
    assert response.status_code == 202, \
E   AssertionError: Promotion request must return 202 Accepted for async processing
E   assert 404 == 202
E    +  where 404 = <Response [404 Not Found]>.status_code
_________________ test_promotions_endpoint_creates_audit_event _________________
tests/unit/test_promotions_endpoint.py:113: in test_promotions_endpoint_creates_audit_event
    with patch("services.api.main.submit_promotion_request") as mock_submit, \
/usr/lib/python3.10/unittest/mock.py:1447: in __enter__
    original, local = self.get_original()
/usr/lib/python3.10/unittest/mock.py:1420: in get_original
    raise AttributeError(
E   AttributeError: <module 'services.api.main' from '/sessions/eloquent-great-ptolemy/mnt/fxlab/services/api/main.py'> does not have the attribute 'audit_service'
... (157 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/routes/promotions.py
    wrote: libs/contracts/promotion.py
    wrote: libs/contracts/enums.py
    wrote: services/api/main.py
    retry 1 for tests/unit/test_promotions_endpoint.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
________ ERROR at setup of test_promotions_endpoint_creates_audit_event ________
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_ ERROR at setup of test_promotions_endpoint_validates_target_environment_enum _
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:22: in <module>
... (151 more lines truncated)
```
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/promotions.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
________ ERROR at setup of test_promotions_endpoint_creates_audit_event ________
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_ ERROR at setup of test_promotions_endpoint_validates_target_environment_enum _
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (151 more lines truncated)
```

## 2026-03-19T20:12:45Z  File: tests/unit/test_runs_readiness_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________ ERROR at setup of test_readiness_endpoint_is_read_only ____________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
______ ERROR at setup of test_readiness_report_includes_scoring_evidence _______
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (144 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/main.py
    wrote: services/__init__.py
    wrote: services/api/__init__.py
    wrote: services/api/routes/__init__.py
    retry 1 for tests/unit/test_runs_readiness_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________ ERROR at setup of test_readiness_endpoint_is_read_only ____________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
______ ERROR at setup of test_readiness_report_includes_scoring_evidence _______
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
... (144 more lines truncated)
```
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/readiness.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/readiness.py
    wrote (retry 1): services/api/routes/readiness.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/readiness.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________ ERROR at setup of test_readiness_endpoint_is_read_only ____________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
______ ERROR at setup of test_readiness_report_includes_scoring_evidence _______
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
... (144 more lines truncated)
```

## 2026-03-19T20:14:10Z  File: tests/unit/test_runs_results_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_handles_service_errors_gracefully ___
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_does_not_compute_readiness_locally __
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
... (144 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    retry 1 for tests/unit/test_runs_results_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_handles_service_errors_gracefully ___
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_does_not_compute_readiness_locally __
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
... (144 more lines truncated)
```
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/__init__.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_handles_service_errors_gracefully ___
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_does_not_compute_readiness_locally __
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (144 more lines truncated)
```
```
============================= test session starts ==============================
collected 139 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [  8%]
tests/integration/test_m0_backend_api_importability.py F.....            [ 12%]
tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [ 20%]
tests/unit/test_artifact_storage_interface.py ................           [ 31%]
tests/unit/test_m0_frontend_structure.py .......F                        [ 37%]
tests/unit/test_m0_project_structure.py ................................ [ 60%]
........................                                                 [ 77%]
tests/unit/test_metadata_database_interface.py ............              [ 86%]
tests/unit/test_promotions_endpoint.py EEEEEEE                           [ 91%]
tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [ 95%]
tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
... (344 more lines truncated)
```

## 2026-03-19T20:15:40Z  S4 M0 — round 2/3, 7 file(s)


## 2026-03-19T20:15:41Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

tests/acceptance/test_m0_bootstrap.py::test_api_health_route_importable
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             42     11    74%   44-46, 56, 60, 83, 87-91
... (109 more lines truncated)
```
    ENV_SKIP — missing: docker (container runtime not available)

## 2026-03-19T20:15:50Z  File: tests/integration/test_m0_backend_api_importability.py

```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             42     11    74%   44-46, 56, 60, 83, 87-91
... (109 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/strategies.py
    wrote: services/api/routes/charts.py
    wrote: services/api/routes/governance.py
    wrote: services/api/routes/queues.py
    wrote: services/api/routes/feeds.py
    retry 1 for tests/integration/test_m0_backend_api_importability.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             42     11    74%   44-46, 56, 60, 83, 87-91
... (110 more lines truncated)
```
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/strategies.py
    wrote (retry 1): services/api/routes/charts.py
    wrote (retry 1): services/api/routes/governance.py
    wrote (retry 1): services/api/routes/queues.py
```
============================= test session starts ==============================
collected 6 items

tests/integration/test_m0_backend_api_importability.py F.....            [100%]

=================================== FAILURES ===================================
_______________ test_ac9_phase1_health_endpoint_returns_success ________________
tests/integration/test_m0_backend_api_importability.py:15: in test_ac9_phase1_health_endpoint_returns_success
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/fastapi/security/oauth2.py:353: UserWarning: A custom validator is returning a value other than `self`.
  Returning anything other than `self` from a top level model validator isn't supported when validating via `__init__`.
  See the `model_validator` docs (https://docs.pydantic.dev/latest/concepts/validators/#model-validators) for more details.
    ] = OAuthFlowsModel(),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             42     11    74%   44-46, 56, 60, 83, 87-91
... (110 more lines truncated)
```

## 2026-03-19T20:17:00Z  File: tests/unit/test_api_bootstrap.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:70: in test_ac2_runs_readiness_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_________________ test_ac2_promotions_request_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:86: in test_ac2_promotions_request_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__________________ test_ac2_approvals_approve_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:108: in test_ac2_approvals_approve_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
... (173 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/__init__.py
    wrote: services/api/__init__.py
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    wrote: services/api/routes/promotions.py
    wrote: services/api/routes/approvals.py
    wrote: services/api/routes/audit.py
    retry 1 for tests/unit/test_api_bootstrap.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:70: in test_ac2_runs_readiness_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_________________ test_ac2_promotions_request_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:86: in test_ac2_promotions_request_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__________________ test_ac2_approvals_approve_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:108: in test_ac2_approvals_approve_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
... (173 more lines truncated)
```
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/routes/approvals.py
    wrote (retry 1): services/api/routes/audit.py
```
============================= test session starts ==============================
collected 10 items

tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [100%]

=================================== FAILURES ===================================
__________________ test_ac1_fastapi_application_module_exists __________________
tests/unit/test_api_bootstrap.py:23: in test_ac1_fastapi_application_module_exists
    from services.api import main
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__________________ test_ac1_application_has_title_and_version __________________
tests/unit/test_api_bootstrap.py:36: in test_ac1_application_has_title_and_version
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________________ test_ac2_runs_results_endpoint_exists _____________________
tests/unit/test_api_bootstrap.py:51: in test_ac2_runs_results_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___________________ test_ac2_runs_readiness_endpoint_exists ____________________
tests/unit/test_api_bootstrap.py:70: in test_ac2_runs_readiness_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_________________ test_ac2_promotions_request_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:86: in test_ac2_promotions_request_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__________________ test_ac2_approvals_approve_endpoint_exists __________________
tests/unit/test_api_bootstrap.py:108: in test_ac2_approvals_approve_endpoint_exists
    from services.api.main import app
services/api/main.py:21: in <module>
... (173 more lines truncated)
```

## 2026-03-19T20:18:16Z  File: tests/unit/test_m0_frontend_structure.py

```
============================= test session starts ==============================
collected 8 items

tests/unit/test_m0_frontend_structure.py .......F                        [100%]

=================================== FAILURES ===================================
_________________________ test_ac8_npm_build_succeeds __________________________
tests/unit/test_m0_frontend_structure.py:152: in test_ac8_npm_build_succeeds
    assert result.returncode == 0, f"npm run build failed with exit code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
E   AssertionError: npm run build failed with exit code 127
E     stdout: 
E     > fxlab-frontend@0.0.0 build
E     > tsc && vite build
E     
E     
E     stderr: sh: 1: tsc: not found
E     
E   assert 127 == 0
E    +  where 127 = CompletedProcess(args=['npm', 'run', 'build'], returncode=127, stdout='\n> fxlab-frontend@0.0.0 build\n> tsc && vite build\n\n', stderr='sh: 1: tsc: not found\n').returncode
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      1     0%   7
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
... (113 more lines truncated)
```
    ENV_SKIP — missing: npm build environment (node_modules not installed — run 'npm install' in the project root first)

## 2026-03-19T20:18:25Z  File: tests/unit/test_promotions_endpoint.py

```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
________ ERROR at setup of test_promotions_endpoint_creates_audit_event ________
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_ ERROR at setup of test_promotions_endpoint_validates_target_environment_enum _
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (152 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/promotions.py
    retry 1 for tests/unit/test_promotions_endpoint.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
________ ERROR at setup of test_promotions_endpoint_creates_audit_event ________
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_ ERROR at setup of test_promotions_endpoint_validates_target_environment_enum _
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:20: in <module>
... (152 more lines truncated)
```
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/promotions.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/promotions.py
```
============================= test session starts ==============================
collected 7 items

tests/unit/test_promotions_endpoint.py EEEEEEE                           [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
________ ERROR at setup of test_promotions_endpoint_creates_audit_event ________
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_ ERROR at setup of test_promotions_endpoint_validates_target_environment_enum _
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (152 more lines truncated)
```

## 2026-03-19T20:19:54Z  File: tests/unit/test_runs_readiness_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________ ERROR at setup of test_readiness_endpoint_is_read_only ____________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
______ ERROR at setup of test_readiness_report_includes_scoring_evidence _______
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (145 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    retry 1 for tests/unit/test_runs_readiness_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________ ERROR at setup of test_readiness_endpoint_is_read_only ____________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
______ ERROR at setup of test_readiness_report_includes_scoring_evidence _______
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (145 more lines truncated)
```
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/readiness.py
    wrote (retry 1): services/api/__init__.py
    wrote (retry 1): services/__init__.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [100%]

==================================== ERRORS ====================================
________ ERROR at setup of test_readiness_endpoint_requires_valid_ulid _________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_readiness_endpoint_returns_404_for_nonexistent_run ___
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_response_includes_grade_and_blockers _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_readiness_blockers_include_owner_and_next_step _____
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____________ ERROR at setup of test_readiness_endpoint_is_read_only ____________
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
______ ERROR at setup of test_readiness_report_includes_scoring_evidence _______
tests/unit/test_runs_readiness_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (145 more lines truncated)
```

## 2026-03-19T20:21:03Z  File: tests/unit/test_runs_results_endpoint.py

```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_handles_service_errors_gracefully ___
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_does_not_compute_readiness_locally __
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (145 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/runs.py
    retry 1 for tests/unit/test_runs_results_endpoint.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_handles_service_errors_gracefully ___
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_does_not_compute_readiness_locally __
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (145 more lines truncated)
```
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/routes/__init__.py
    wrote (retry 1): services/api/routes/runs.py
    wrote (retry 1): services/__init__.py
    wrote (retry 1): services/api/__init__.py
```
============================= test session starts ==============================
collected 6 items

tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
______ ERROR at setup of test_results_endpoint_requires_valid_ulid_format ______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
___ ERROR at setup of test_results_endpoint_returns_404_for_nonexistent_run ____
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_returns_structured_json ________
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_results_endpoint_includes_metadata_fields _______
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_handles_service_errors_gracefully ___
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
__ ERROR at setup of test_results_endpoint_does_not_compute_readiness_locally __
tests/unit/test_runs_results_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
... (145 more lines truncated)
```
```
============================= test session starts ==============================
collected 139 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [  8%]
tests/integration/test_m0_backend_api_importability.py F.....            [ 12%]
tests/unit/test_api_bootstrap.py FFFFFFFFFF                              [ 20%]
tests/unit/test_artifact_storage_interface.py ................           [ 31%]
tests/unit/test_m0_frontend_structure.py .......F                        [ 37%]
tests/unit/test_m0_project_structure.py ................................ [ 60%]
........................                                                 [ 77%]
tests/unit/test_metadata_database_interface.py ............              [ 86%]
tests/unit/test_promotions_endpoint.py EEEEEEE                           [ 91%]
tests/unit/test_runs_readiness_endpoint.py EEEEEE                        [ 95%]
tests/unit/test_runs_results_endpoint.py EEEEEE                          [100%]

==================================== ERRORS ====================================
_______ ERROR at setup of test_promotions_endpoint_requires_candidate_id _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_requires_target_environment ____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
_______ ERROR at setup of test_promotions_endpoint_validates_ulid_format _______
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
____ ERROR at setup of test_promotions_endpoint_returns_job_id_immediately _____
tests/unit/test_promotions_endpoint.py:15: in client
    from services.api.main import app
services/api/main.py:21: in <module>
    lifespan=lifespan,
E   NameError: name 'lifespan' is not defined
... (345 more lines truncated)
```
    OSCILLATION: fingerprint ['tests/integration/test_m0_backend_api_importability.py', 'tests/unit/test_api_bootstrap.py', 'tests/unit/test_promotions_endpoint.py', 'tests/unit/test_runs_readiness_endpoint.py', 'tests/unit/test_runs_results_endpoint.py'] seen at round 2 and again at round 3

## 2026-03-19T21:45:02Z  M1 S3 RED baseline

Acceptance criteria (0):

RED failures S4 must fix:

```
============================= test session starts ==============================
collected 153 items / 2 errors

==================================== ERRORS ====================================
______ ERROR collecting tests/integration/test_docker_compose_services.py ______
ImportError while importing test module '/sessions/eloquent-great-ptolemy/mnt/fxlab/tests/integration/test_docker_compose_services.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/integration/test_docker_compose_services.py:16: in <module>
    import yaml
E   ModuleNotFoundError: No module named 'yaml'
______ ERROR collecting tests/integration/test_docker_compose_startup.py _______
ImportError while importing test module '/sessions/eloquent-great-ptolemy/mnt/fxlab/tests/integration/test_docker_compose_startup.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/integration/test_docker_compose_startup.py:12: in <module>
    import requests
E   ModuleNotFoundError: No module named 'requests'
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
ERROR tests/integration/test_docker_compose_services.py
ERROR tests/integration/test_docker_compose_startup.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
========================= 1 warning, 2 errors in 1.08s =========================
```

## 2026-03-19T21:46:57Z  S4 M1 — round 1/3, 2 file(s)


## 2026-03-19T21:46:57Z  File: tests/integration/test_docker_compose_services.py

```
============================= test session starts ==============================
collected 26 items

tests/integration/test_docker_compose_services.py ..FFFFFFFFFFFFFFFFFFFF [ 84%]
sFFF                                                                     [100%]

=================================== FAILURES ===================================
_________________________ test_ac1_api_service_defined _________________________
tests/integration/test_docker_compose_services.py:55: in test_ac1_api_service_defined
    assert 'api' in compose_config['services'], "'api' service not defined"
E   AssertionError: 'api' service not defined
E   assert 'api' in {'health': {'build': {'context': './services/health', 'dockerfile': 'Dockerfile'}, 'container_name': 'fxlab-health', '...: '10s', 'retries': 3, 'start_period': '5s', 'test': ['CMD', 'curl', '-f', 'http://localhost:8000/health'], ...}, ...}}
_________________________ test_ac1_web_service_defined _________________________
tests/integration/test_docker_compose_services.py:61: in test_ac1_web_service_defined
    assert 'web' in compose_config['services'], "'web' service not defined"
E   AssertionError: 'web' service not defined
E   assert 'web' in {'health': {'build': {'context': './services/health', 'dockerfile': 'Dockerfile'}, 'container_name': 'fxlab-health', '...: '10s', 'retries': 3, 'start_period': '5s', 'test': ['CMD', 'curl', '-f', 'http://localhost:8000/health'], ...}, ...}}
______________________ test_ac1_postgres_service_defined _______________________
tests/integration/test_docker_compose_services.py:67: in test_ac1_postgres_service_defined
    assert 'postgres' in compose_config['services'], "'postgres' service not defined"
E   AssertionError: 'postgres' service not defined
E   assert 'postgres' in {'health': {'build': {'context': './services/health', 'dockerfile': 'Dockerfile'}, 'container_name': 'fxlab-health', '...: '10s', 'retries': 3, 'start_period': '5s', 'test': ['CMD', 'curl', '-f', 'http://localhost:8000/health'], ...}, ...}}
________________________ test_ac1_redis_service_defined ________________________
tests/integration/test_docker_compose_services.py:73: in test_ac1_redis_service_defined
    assert 'redis' in compose_config['services'], "'redis' service not defined"
E   AssertionError: 'redis' service not defined
E   assert 'redis' in {'health': {'build': {'context': './services/health', 'dockerfile': 'Dockerfile'}, 'container_name': 'fxlab-health', '...: '10s', 'retries': 3, 'start_period': '5s', 'test': ['CMD', 'curl', '-f', 'http://localhost:8000/health'], ...}, ...}}
_____________________ test_ac2_api_service_has_healthcheck _____________________
tests/integration/test_docker_compose_services.py:78: in test_ac2_api_service_has_healthcheck
    api_service = compose_config['services']['api']
E   KeyError: 'api'
______________________ test_ac2_api_healthcheck_has_test _______________________
tests/integration/test_docker_compose_services.py:84: in test_ac2_api_healthcheck_has_test
    api_healthcheck = compose_config['services']['api']['healthcheck']
E   KeyError: 'api'
________________ test_ac2_api_healthcheck_uses_health_endpoint _________________
tests/integration/test_docker_compose_services.py:90: in test_ac2_api_healthcheck_uses_health_endpoint
    api_healthcheck = compose_config['services']['api']['healthcheck']
E   KeyError: 'api'
_____________________ test_ac2_web_service_has_healthcheck _____________________
... (224 more lines truncated)
```
    ENV_SKIP — missing: docker (container runtime not available), redis (Redis server / CLI not available)

## 2026-03-19T21:47:07Z  File: tests/unit/test_fastapi_main_structure.py

```
============================= test session starts ==============================
collected 10 items

tests/unit/test_fastapi_main_structure.py ......F...                     [100%]

=================================== FAILURES ===================================
_________________________ test_ac2_health_status_is_ok _________________________
tests/unit/test_fastapi_main_structure.py:85: in test_ac2_health_status_is_ok
    assert data.get("status") == "ok", \
E   AssertionError: Expected status='ok', got status='healthy'
E   assert 'healthy' == 'ok'
E     
E     - ok
E     + healthy
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.12-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          1      0   100%
libs/contracts/artifact.py                         33     33     0%   7-80
libs/contracts/audit.py                            28     28     0%   5-43
libs/contracts/base.py                             42     11    74%   44-46, 56, 60, 83, 87-91
libs/contracts/chart.py                            24     24     0%   8-64
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
... (111 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: services/api/main.py
    promoted to passing: tests/unit/test_fastapi_main_structure.py
```
============================= test session starts ==============================
collected 191 items

tests/acceptance/test_m0_bootstrap.py ............                       [  6%]
tests/api/test_main.py F..                                               [  7%]
tests/integration/test_docker_compose_services.py ..FFFFFFFFFFFFFFFFFFFF [ 19%]
sFFF                                                                     [ 21%]
tests/integration/test_docker_compose_startup.py ssssssssssss            [ 27%]
tests/integration/test_m0_backend_api_importability.py F.....            [ 30%]
tests/test_api.py F                                                      [ 31%]
tests/unit/test_api_bootstrap.py ..........                              [ 36%]
tests/unit/test_artifact_storage_interface.py ................           [ 45%]
tests/unit/test_fastapi_main_structure.py ..........                     [ 50%]
tests/unit/test_m0_frontend_structure.py ........                        [ 54%]
tests/unit/test_m0_project_structure.py ................................ [ 71%]
........................                                                 [ 83%]
tests/unit/test_metadata_database_interface.py ............              [ 90%]
tests/unit/test_promotions_endpoint.py .......                           [ 93%]
tests/unit/test_runs_readiness_endpoint.py ......                        [ 96%]
tests/unit/test_runs_results_endpoint.py ......                          [100%]

=================================== FAILURES ===================================
______________________________ test_health_check _______________________________
tests/api/test_main.py:21: in test_health_check
    assert data["status"] == "healthy"
E   AssertionError: assert 'ok' == 'healthy'
E     
E     - healthy
E     + ok
----------------------------- Captured stdout call -----------------------------
2026-03-19 17:47:39 [debug    ] health_check.called
_________________________ test_ac1_api_service_defined _________________________
tests/integration/test_docker_compose_services.py:55: in test_ac1_api_service_defined
    assert 'api' in compose_config['services'], "'api' service not defined"
E   AssertionError: 'api' service not defined
E   assert 'api' in {'health': {'build': {'context': './services/health', 'dockerfile': 'Dockerfile'}, 'container_name': 'fxlab-health', '...: '10s', 'retries': 3, 'start_period': '5s', 'test': ['CMD', 'curl', '-f', 'http://localhost:8000/health'], ...}, ...}}
_________________________ test_ac1_web_service_defined _________________________
tests/integration/test_docker_compose_services.py:61: in test_ac1_web_service_defined
    assert 'web' in compose_config['services'], "'web' service not defined"
E   AssertionError: 'web' service not defined
... (265 more lines truncated)
```
    REGRESSION ROLLBACK: 3 regression(s); 1 file(s) restored from journal

## 2026-03-19T22:00:55Z  M2 S3 RED baseline

Acceptance criteria (0):

RED failures S4 must fix:

```
============================= test session starts ==============================
collected 19 items / 2 errors

==================================== ERRORS ====================================
______________________ ERROR collecting tests/integration ______________________
/usr/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
<frozen importlib._bootstrap>:1050: in _gcd_import
    ???
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
.venv/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:197: in exec_module
    exec(co, module.__dict__)
tests/integration/conftest.py:47: in <module>
    from libs.contracts.models import Base
E   ModuleNotFoundError: No module named 'libs.contracts.models'
_________________________ ERROR collecting tests/unit __________________________
/usr/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
<frozen importlib._bootstrap>:1050: in _gcd_import
    ???
<frozen importlib._bootstrap>:1027: in _find_and_load
    ???
<frozen importlib._bootstrap>:1006: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:688: in _load_unlocked
    ???
.venv/lib/python3.10/site-packages/_pytest/assertion/rewrite.py:197: in exec_module
    exec(co, module.__dict__)
tests/unit/conftest.py:116: in <module>
    from libs.contracts.models import Base
E   ModuleNotFoundError: No module named 'libs.contracts.models'
=============================== warnings summary ===============================
.venv/lib/python3.10/site-packages/coverage/core.py:108
  /sessions/eloquent-great-ptolemy/mnt/fxlab/.venv/lib/python3.10/site-packages/coverage/core.py:108: CoverageWarning: Couldn't import C tracer: No module named 'coverage.tracer' (no-ctracer); see https://coverage.readthedocs.io/en/7.13.4/messages.html#warning-no-ctracer
    warn(f"Couldn't import C tracer: {IMPORT_ERROR}", slug="no-ctracer", once=True)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
ERROR tests/integration - ModuleNotFoundError: No module named 'libs.contract...
ERROR tests/unit - ModuleNotFoundError: No module named 'libs.contracts.models'
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
========================= 1 warning, 2 errors in 1.26s =========================
```

---
## M5 — Artifact Registry + Storage Abstraction — 2026-03-27

### Summary
Implemented the full M5 milestone: Artifact Registry API endpoints + Storage Abstraction layer.

### New files
- `libs/storage/base.py` — canonical `ArtifactStorageBase(ABC)` consolidating 3 competing legacy ABCs
- `libs/storage/local_storage.py` — `LocalArtifactStorage` filesystem-backed implementation
- `libs/contracts/interfaces/artifact_repository.py` — `ArtifactRepositoryInterface(ABC)`
- `libs/contracts/mocks/mock_artifact_repository.py` — `MockArtifactRepository` (100% coverage)
- `tests/unit/test_m5_artifact_registry.py` — 42 tests covering all M5 components

### Modified files
- `services/api/routes/artifacts.py` — full implementation (was stub); GET /artifacts + GET /artifacts/{id}/download
- `services/api/main.py` — registered artifacts.router
- `libs/storage/__init__.py` — exposed ArtifactStorageBase and LocalArtifactStorage from canonical base
- `tests/conftest.py` — fixed LL-003 (12 plain functions → @pytest.fixture decorated)
- `tests/integration/conftest.py` — fixed LL-003 + LL-S004 SAVEPOINT isolation
- `pytest.ini` / `pyproject.toml` — added norecursedirs to prevent .venv test collection

### Meta-fixes applied
- pytest.ini norecursedirs: prevents discovery of third-party test suites in .venv
- conftest.py full rewrite: all fixtures properly decorated (LL-003)
- integration/conftest.py: SAVEPOINT isolation for SQLAlchemy tests (LL-005)

### Test results
- 307 unit tests passing (42 new M5 + 265 prior), 0 failures, 0 regressions
- Coverage: routes/artifacts.py 92%, mock_artifact_repository.py 100%, local_storage.py 91%

### Lessons learned
- LL-008: FastAPI response_model serialization → use explicit model_dump() + JSONResponse
- LL-009: ruff/mypy wheel binaries are arch-specific; cannot run in cross-arch sandbox
