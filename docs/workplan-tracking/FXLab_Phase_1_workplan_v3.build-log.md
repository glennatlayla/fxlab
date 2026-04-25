
## 2026-03-16T17:45:23Z  M0 S3 RED baseline

These failures define the RED baseline that S4 GREEN must fix:

```
..........FF....FFF.F.......FE.E.E.E.E.E.E.E.E.EFEFEFE                   [100%]
==================================== ERRORS ====================================
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_connect_establishes_connection _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_connect_with_invalid_credentials_raises_error _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_health_check_succeeds_when_connected _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_health_check_fails_when_disconnected _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_disconnect_closes_connection_gracefully _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_disconnect_is_idempotent _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_begin_transaction_returns_transaction_context _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_commit_transaction_persists_changes _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_rollback_transaction_discards_changes _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_transaction_auto_rollback_on_exception _
tests/conftest.py:30: in mock_metadata_db
    m
```

## 2026-03-16T17:48:35Z  M0 S4 attempt 1

```
..........FF....FFF.F.......FE.E.E.E.E.E.E.E.E.EFEFEFE                   [100%]
==================================== ERRORS ====================================
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_connect_establishes_connection _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_connect_with_invalid_credentials_raises_error _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_health_check_succeeds_when_connected _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_health_check_fails_when_disconnected _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_disconnect_closes_connection_gracefully _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_disconnect_is_idempotent _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_begin_transaction_returns_transaction_context _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_commit_transaction_persists_changes _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_rollback_transaction_discards_changes _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_transaction_auto_rollback_on_exception _
tests/conftest.py:30: in mock_metadata_db
    m
```

## 2026-03-16T17:50:21Z  M0 S4 attempt 2

```
..........FF....FFF.F.......FE.E.E.E.E.E.E.E.E.EFEFEFE                   [100%]
==================================== ERRORS ====================================
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_connect_establishes_connection _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_connect_with_invalid_credentials_raises_error _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_health_check_succeeds_when_connected _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_health_check_fails_when_disconnected _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_disconnect_closes_connection_gracefully _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_disconnect_is_idempotent _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_begin_transaction_returns_transaction_context _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_commit_transaction_persists_changes _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_rollback_transaction_discards_changes _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_transaction_auto_rollback_on_exception _
tests/conftest.py:30: in mock_metadata_db
    m
```

## 2026-03-16T17:51:47Z  M0 S4 attempt 3

```
..........FF....FFF.F.......FE.E.E.E.E.E.E.E.E.EFEFEFE                   [100%]
==================================== ERRORS ====================================
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_connect_establishes_connection _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_connect_with_invalid_credentials_raises_error _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_health_check_succeeds_when_connected _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_health_check_fails_when_disconnected _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_disconnect_closes_connection_gracefully _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseConnection.test_database_disconnect_is_idempotent _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_begin_transaction_returns_transaction_context _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_commit_transaction_persists_changes _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_rollback_transaction_discards_changes _
tests/conftest.py:30: in mock_metadata_db
    mock_db.close.assert_called()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:918: in assert_called
    raise AssertionError(msg)
E   AssertionError: Expected 'close' to have been called.
_ ERROR at teardown of TestMetadataDatabaseTransactions.test_database_transaction_auto_rollback_on_exception _
tests/conftest.py:30: in mock_metadata_db
    m
```

## 2026-03-16T18:12:03Z  M0 S4 STILL FAILING tests/acceptance/test_m0_bootstrap.py

```
..........FF                                                             [100%]
=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:156: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/contracts/base.py:3: in <module>
    from pydantic import BaseModel, ConfigDict, field_validator
E   ModuleNotFoundError: No module named 'pydantic'
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:2: in <module>
    import structlog
E   ModuleNotFoundError: No module named 'structlog'
=========================== short test summary info ============================
FAILED tests/acceptance/test_m0_bootstrap.py::test_contracts_importable - Mod...
FAILED tests/acceptance/test_m0_bootstrap.py::test_api_health_route_importable
2 failed, 10 passed in 0.10s
```

## 2026-03-16T18:12:26Z  M0 S4 STILL FAILING tests/unit/test_artifact_storage_interface.py

```
ImportError while loading conftest '/Users/gjohnson/Documents/Coding Projects/fxlab/tests/conftest.py'.
tests/conftest.py:9: in <module>
    import ulid
E   ModuleNotFoundError: No module named 'ulid'
```

## 2026-03-16T18:13:09Z  M0 S4 STILL FAILING tests/unit/test_metadata_database_interface.py

```
ImportError while loading conftest '/Users/gjohnson/Documents/Coding Projects/fxlab/tests/conftest.py'.
tests/conftest.py:8: in <module>
    import ulid
E   ModuleNotFoundError: No module named 'ulid'
```

## 2026-03-16T18:23:25Z  M0 S4 STILL FAILING tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
E   ModuleNotFoundError: No module named 'services.api'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      0   100%
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      0   100%
libs/contracts/errors.py                      5      3    40%   7-9
libs/contracts/health.py                     25     25     0%   3-70
libs/contracts/storage.py                    25     25     0%   3-51
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           0      0   100%
libs/db/metadata.py                          15     15     0%   7-112
libs/feeds/__init__.py                        0      0   100%
libs/jobs/__init__.py                         0      0   100%
libs/parity/__init__.py                       0      0   100%
libs/quality/__init__.py                      0      0   100%
libs/storag
```

## 2026-03-16T18:24:17Z  M0 S4 FIXED tests/unit/test_artifact_storage_interface.py

Files written: ['libs/contracts/storage.py', 'libs/storage/__init__.py', 'libs/storage/minio_storage.py', 'tests/conftest.py']

## 2026-03-16T18:24:57Z  M0 S4 STILL FAILING tests/unit/test_metadata_database_interface.py

```
============================= test session starts ==============================
collected 13 items

tests/unit/test_metadata_database_interface.py .......FFFF..             [100%]

=================================== FAILURES ===================================
_ TestMetadataDatabaseTransactions.test_database_commit_transaction_persists_changes _
tests/unit/test_metadata_database_interface.py:153: in test_database_commit_transaction_persists_changes
    mock_transaction.commit.assert_called_once()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:928: in assert_called_once
    raise AssertionError(msg)
E   AssertionError: Expected 'commit' to have been called once. Called 0 times.
_ TestMetadataDatabaseTransactions.test_database_rollback_transaction_discards_changes _
tests/unit/test_metadata_database_interface.py:172: in test_database_rollback_transaction_discards_changes
    mock_transaction.rollback.assert_called_once()
/opt/homebrew/Cellar/python@3.12/3.12.13/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/mock.py:928: in assert_called_once
    raise AssertionError(msg)
E   AssertionError: Expected 'rollback' to have been called once. Called 0 times.
_ TestMetadataDatabaseTransactions.test_database_transaction_auto_rollback_on_exception _
tests/unit/test_metadata_database_interface.py:197: in test_database_transaction_auto_rollback_on_exception
    assert mock_transaction.__exit__.called, \
E   AssertionError: Transaction context should handle exception
E   assert False
E    +  where False = <MagicMock name='mock.begin_transaction().__exit__' id='4480944752'>.called
E    +    where <MagicMock name='mock.begin_transaction().__exit__' id='4480944752'> = <MagicMock name='mock.begin_transaction()' id='4481254176'>.__exit__
_ TestMetadataDatabaseQueryExecution.test_database_execute_query_returns_results _
tests/unit/test_metadata_database_interface.py:222: in test_database_execute_que
```

## 2026-03-16T18:28:26Z  M0 S4 STILL FAILING tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
E   ModuleNotFoundError: No module named 'services.api'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      0   100%
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      0   100%
libs/contracts/errors.py                      5      3    40%   7-9
libs/contracts/health.py                     12     12     0%   2-21
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                          10     10     0%   5-118
libs/db/metadata.py                          15     15     0%   7-112
libs/feeds/__init__.py                        0      0   100%
libs/jobs/__init__.py                         0      0   100%
libs/parity/__init__.py                       0      0   100%
libs/quality/__init__.py                      0      0   100%
li
```

## 2026-03-16T18:28:56Z  M0 S4 FIXED tests/unit/test_artifact_storage_interface.py

Files written: ['tests/conftest.py', 'libs/storage/__init__.py', 'libs/storage/interface.py']

## 2026-03-16T18:29:25Z  M0 S4 STILL FAILING tests/unit/test_metadata_database_interface.py

```
============================= test session starts ==============================
collected 13 items

tests/unit/test_metadata_database_interface.py F...........F             [100%]

=================================== FAILURES ===================================
_ TestMetadataDatabaseConnection.test_database_connect_establishes_connection __
tests/unit/test_metadata_database_interface.py:27: in test_database_connect_establishes_connection
    assert mock_metadata_db.is_connected() is True, \
E   AssertionError: Database should be connected after successful connect()
E   assert <MagicMock name='mock.is_connected()' id='4457867568'> is True
E    +  where <MagicMock name='mock.is_connected()' id='4457867568'> = <MagicMock name='mock.is_connected' id='4457449472'>()
E    +    where <MagicMock name='mock.is_connected' id='4457449472'> = <MagicMock spec='MetadataDatabase' id='4437867264'>.is_connected
_ TestMetadataDatabaseQueryExecution.test_database_execute_logs_correlation_id _
tests/unit/test_metadata_database_interface.py:271: in test_database_execute_logs_correlation_id
    assert mock_logger.info.called or mock_logger.debug.called, \
E   AssertionError: Database should log queries with correlation_id
E   assert (False or False)
E    +  where False = <MagicMock name='mock.logger.info' id='4457870880'>.called
E    +    where <MagicMock name='mock.logger.info' id='4457870880'> = <MagicMock name='mock.logger' id='4457866512'>.info
E    +  and   False = <MagicMock name='mock.logger.debug' id='4457872704'>.called
E    +    where <MagicMock name='mock.logger.debug' id='4457872704'> = <MagicMock name='mock.logger' id='4457866512'>.debug
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py
```

## 2026-03-16T19:14:28Z  S4 M0 — targeting 3 file(s)


## 2026-03-16T19:14:28Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
E   ModuleNotFoundError: No module named 'services.api'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      0   100%
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      0   100%
libs/contracts/errors.py                      5      3    40%   7-9
libs/contracts/health.py                     12     12     0%   2-21
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      0   100%
libs/db/metadata.py                          15     15     0%   7-112
libs/db/metadata_database.py                 51     33    35%   17-19, 22-26, 29-35, 39-42, 49-52, 65-66, 78-82, 91, 103-108, 118-125, 140-144, 163-172
libs/feeds/__init__.py                        0      0   100%
libs/jobs/__init__.py                         0      0   100%
libs/parity/__init__.py                       0      0   100%
libs/quality/__init__.py                      0      0   100%
libs/storage/__init__.py                      0      0   100%
libs/storage/interface.py                    27     27     0%   6-173
libs/storage/minio_storage.py               109    109     0%   6-431
libs/telemetry/__init__.py                    0      0   100%
libs/utils/__init__.py                        0      0   100%
services/alerting/__init__.py                 0      0   100%
... (16 more lines truncated)
```
    wrote: services/api/__init__.py
    wrote: services/api/main.py
    wrote: libs/contracts/health.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
E   ModuleNotFoundError: No module named 'services.api'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      0   100%
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      0   100%
libs/contracts/errors.py                      5      3    40%   7-9
libs/contracts/health.py                     15     15     0%   2-36
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      0   100%
libs/db/metadata.py                          15     15     0%   7-112
libs/db/metadata_database.py                 51     33    35%   17-19, 22-26, 29-35, 39-42, 49-52, 65-66, 78-82, 91, 103-108, 118-125, 140-144, 163-172
libs/feeds/__init__.py                        0      0   100%
libs/jobs/__init__.py                         0      0   100%
libs/parity/__init__.py                       0      0   100%
libs/quality/__init__.py                      0      0   100%
libs/storage/__init__.py                      0      0   100%
libs/storage/interface.py                    27     27     0%   6-173
libs/storage/minio_storage.py               109    109     0%   6-431
libs/telemetry/__init__.py                    0      0   100%
libs/utils/__init__.py                        0      0   100%
services/alerting/__init__.py                 0      0   100%
... (16 more lines truncated)
```

## 2026-03-16T19:14:48Z  File: tests/unit/test_artifact_storage_interface.py

```
============================= test session starts ==============================
collected 16 items

tests/unit/test_artifact_storage_interface.py EEEEEEEEEEEEEEEE           [100%]

==================================== ERRORS ====================================
_ ERROR at setup of TestArtifactStorageInitialization.test_storage_initialize_creates_required_buckets _
file /Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py, line 16
      def test_storage_initialize_creates_required_buckets(
E       fixture 'mock_artifact_storage' not found
>       available fixtures: _class_scoped_runner, _function_scoped_runner, _module_scoped_runner, _package_scoped_runner, _session_faker, _session_scoped_runner, cache, capfd, capfdbinary, caplog, capsys, capsysbinary, capteesys, correlation_id, cov, doctest_namespace, event_loop_policy, faker, mock_logger, mock_metadata_db, monkeypatch, no_cover, pytestconfig, record_property, record_testsuite_property, record_xml_attribute, recwarn, subtests, tmp_path, tmp_path_factory, tmpdir, tmpdir_factory, unused_tcp_port, unused_tcp_port_factory, unused_udp_port, unused_udp_port_factory
>       use 'pytest --fixtures [testpath]' for help on them.

/Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py:16
_ ERROR at setup of TestArtifactStorageInitialization.test_storage_initialize_is_idempotent _
file /Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py, line 33
      def test_storage_initialize_is_idempotent(
E       fixture 'mock_artifact_storage' not found
>       available fixtures: _class_scoped_runner, _function_scoped_runner, _module_scoped_runner, _package_scoped_runner, _session_faker, _session_scoped_runner, cache, capfd, capfdbinary, caplog, capsys, capsysbinary, capteesys, correlation_id, cov, doctest_namespace, event_loop_policy, faker, mock_logger, mock_metadata_db, monkeypatch, no_cover, pytestconfig, record_property, record_testsuite_property, record_xml_attribute, recwarn, subtests, tmp_path, tmp_path_factory, tmpdir, tmpdir_factory, unused_tcp_port, unused_tcp_port_factory, unused_udp_port, unused_udp_port_factory
>       use 'pytest --fixtures [testpath]' for help on them.

/Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py:33
_ ERROR at setup of TestArtifactStorageInitialization.test_storage_health_check_succeeds_when_accessible _
file /Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py, line 51
      def test_storage_health_check_succeeds_when_accessible(
E       fixture 'mock_artifact_storage' not found
>       available fixtures: _class_scoped_runner, _function_scoped_runner, _module_scoped_runner, _package_scoped_runner, _session_faker, _session_scoped_runner, cache, capfd, capfdbinary, caplog, capsys, capsysbinary, capteesys, correlation_id, cov, doctest_namespace, event_loop_policy, faker, mock_logger, mock_metadata_db, monkeypatch, no_cover, pytestconfig, record_property, record_testsuite_property, record_xml_attribute, recwarn, subtests, tmp_path, tmp_path_factory, tmpdir, tmpdir_factory, unused_tcp_port, unused_tcp_port_factory, unused_udp_port, unused_udp_port_factory
>       use 'pytest --fixtures [testpath]' for help on them.

/Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py:51
_ ERROR at setup of TestArtifactStorageInitialization.test_storage_health_check_fails_when_unreachable _
file /Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py, line 67
      def test_storage_health_check_fails_when_unreachable(
E       fixture 'mock_artifact_storage' not found
>       available fixtures: _class_scoped_runner, _function_scoped_runner, _module_scoped_runner, _package_scoped_runner, _session_faker, _session_scoped_runner, cache, capfd, capfdbinary, caplog, capsys, capsysbinary, capteesys, correlation_id, cov, doctest_namespace, event_loop_policy, faker, mock_logger, mock_metadata_db, monkeypatch, no_cover, pytestconfig, record_property, record_testsuite_property, record_xml_attribute, recwarn, subtests, tmp_path, tmp_path_factory, tmpdir, tmpdir_factory, unused_tcp_port, unused_tcp_port_factory, unused_udp_port, unused_udp_port_factory
>       use 'pytest --fixtures [testpath]' for help on them.

/Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py:67
_ ERROR at setup of TestArtifactStoragePutOperations.test_storage_put_artifact_stores_object_with_metadata _
file /Users/gjohnson/Documents/Coding Projects/fxlab/tests/unit/test_artifact_storage_interface.py, line 88
... (155 more lines truncated)
```
    wrote: libs/storage/__init__.py
    wrote: libs/storage/artifact_storage.py
    wrote: tests/conftest.py

## 2026-03-16T19:15:22Z  File: tests/unit/test_metadata_database_interface.py

```
============================= test session starts ==============================
collected 13 items

tests/unit/test_metadata_database_interface.py F...........F             [100%]

=================================== FAILURES ===================================
_ TestMetadataDatabaseConnection.test_database_connect_establishes_connection __
tests/unit/test_metadata_database_interface.py:27: in test_database_connect_establishes_connection
    assert mock_metadata_db.is_connected() is True, \
E   AssertionError: Database should be connected after successful connect()
E   assert <MagicMock name='mock.is_connected()' id='4449171984'> is True
E    +  where <MagicMock name='mock.is_connected()' id='4449171984'> = <MagicMock name='mock.is_connected' id='4449168144'>()
E    +    where <MagicMock name='mock.is_connected' id='4449168144'> = <MagicMock id='4448412032'>.is_connected
_ TestMetadataDatabaseQueryExecution.test_database_execute_logs_correlation_id _
tests/unit/test_metadata_database_interface.py:271: in test_database_execute_logs_correlation_id
    assert mock_logger.info.called or mock_logger.debug.called, \
E   AssertionError: Database should log queries with correlation_id
E   assert (False or False)
E    +  where False = <MagicMock name='mock.logger.info' id='4449137488'>.called
E    +    where <MagicMock name='mock.logger.info' id='4449137488'> = <MagicMock name='mock.logger' id='4449159264'>.info
E    +  and   False = <MagicMock name='mock.logger.debug' id='4449162288'>.called
E    +    where <MagicMock name='mock.logger.debug' id='4449162288'> = <MagicMock name='mock.logger' id='4449159264'>.debug
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      8     0%   2-13
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      6     0%   2-10
libs/contracts/errors.py                      5      5     0%   4-9
libs/contracts/health.py                     15     15     0%   2-36
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      2     0%   3-5
... (32 more lines truncated)
```
    wrote: tests/conftest.py
    wrote: libs/db/__init__.py
    wrote: libs/db/metadata.py
```
============================= test session starts ==============================
collected 13 items

tests/unit/test_metadata_database_interface.py F...........F             [100%]

=================================== FAILURES ===================================
_ TestMetadataDatabaseConnection.test_database_connect_establishes_connection __
tests/unit/test_metadata_database_interface.py:27: in test_database_connect_establishes_connection
    assert mock_metadata_db.is_connected() is True, \
E   AssertionError: Database should be connected after successful connect()
E   assert <MagicMock name='mock.is_connected()' id='4406204160'> is True
E    +  where <MagicMock name='mock.is_connected()' id='4406204160'> = <MagicMock name='mock.is_connected' id='4418432096'>()
E    +    where <MagicMock name='mock.is_connected' id='4418432096'> = <MagicMock id='4417912272'>.is_connected
_ TestMetadataDatabaseQueryExecution.test_database_execute_logs_correlation_id _
tests/unit/test_metadata_database_interface.py:271: in test_database_execute_logs_correlation_id
    assert mock_logger.info.called or mock_logger.debug.called, \
E   AssertionError: Database should log queries with correlation_id
E   assert (False or False)
E    +  where False = <MagicMock name='mock.logger.info' id='4418976944'>.called
E    +    where <MagicMock name='mock.logger.info' id='4418976944'> = <MagicMock name='mock.logger' id='4418969120'>.info
E    +  and   False = <MagicMock name='mock.logger.debug' id='4419013472'>.called
E    +    where <MagicMock name='mock.logger.debug' id='4419013472'> = <MagicMock name='mock.logger' id='4418969120'>.debug
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      8     0%   2-13
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      6     0%   2-10
libs/contracts/errors.py                      5      5     0%   4-9
libs/contracts/health.py                     15     15     0%   2-36
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      2     0%   6-8
... (32 more lines truncated)
```
```
============================= test session starts ==============================
collected 41 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [ 29%]
tests/unit/test_artifact_storage_interface.py ................           [ 68%]
tests/unit/test_metadata_database_interface.py F...........F             [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
E   ModuleNotFoundError: No module named 'services.api'
_ TestMetadataDatabaseConnection.test_database_connect_establishes_connection __
tests/unit/test_metadata_database_interface.py:27: in test_database_connect_establishes_connection
    assert mock_metadata_db.is_connected() is True, \
E   AssertionError: Database should be connected after successful connect()
E   assert <MagicMock name='mock.is_connected()' id='4495621296'> is True
E    +  where <MagicMock name='mock.is_connected()' id='4495621296'> = <MagicMock name='mock.is_connected' id='4495617792'>()
E    +    where <MagicMock name='mock.is_connected' id='4495617792'> = <MagicMock id='4495743824'>.is_connected
_ TestMetadataDatabaseQueryExecution.test_database_execute_logs_correlation_id _
tests/unit/test_metadata_database_interface.py:271: in test_database_execute_logs_correlation_id
    assert mock_logger.info.called or mock_logger.debug.called, \
E   AssertionError: Database should log queries with correlation_id
E   assert (False or False)
E    +  where False = <MagicMock name='mock.logger.info' id='4496191328'>.called
E    +    where <MagicMock name='mock.logger.info' id='4496191328'> = <MagicMock name='mock.logger' id='4496344560'>.info
E    +  and   False = <MagicMock name='mock.logger.debug' id='4496315344'>.called
E    +    where <MagicMock name='mock.logger.debug' id='4496315344'> = <MagicMock name='mock.logger' id='4496344560'>.debug
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      0   100%
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
... (37 more lines truncated)
```

## 2026-03-16T19:39:04Z  S4 M0 — targeting 2 file(s)


## 2026-03-16T19:39:04Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
E   ModuleNotFoundError: No module named 'services.api'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      0   100%
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      0   100%
libs/contracts/errors.py                      5      3    40%   7-9
libs/contracts/health.py                     15     15     0%   2-36
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      2     0%   6-8
libs/db/metadata.py                          93     93     0%   7-326
libs/db/metadata_database.py                 51     51     0%   6-172
libs/feeds/__init__.py                        0      0   100%
libs/jobs/__init__.py                         0      0   100%
libs/parity/__init__.py                       0      0   100%
libs/quality/__init__.py                      0      0   100%
libs/storage/__init__.py                      2      2     0%   5-7
libs/storage/artifact_storage.py             27     27     0%   13-197
libs/storage/interface.py                    27     27     0%   6-173
libs/storage/minio_storage.py               109    109     0%   6-431
libs/telemetry/__init__.py                    0      0   100%
libs/utils/__init__.py                        0      0   100%
... (17 more lines truncated)
```
    wrote: services/api/__init__.py
    wrote: services/api/main.py
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/health.py
    wrote: libs/contracts/health.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
E   ModuleNotFoundError: No module named 'services.api'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      0   100%
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      0   100%
libs/contracts/errors.py                      5      3    40%   7-9
libs/contracts/health.py                     17     17     0%   2-27
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      2     0%   6-8
libs/db/metadata.py                          93     93     0%   7-326
libs/db/metadata_database.py                 51     51     0%   6-172
libs/feeds/__init__.py                        0      0   100%
libs/jobs/__init__.py                         0      0   100%
libs/parity/__init__.py                       0      0   100%
libs/quality/__init__.py                      0      0   100%
libs/storage/__init__.py                      2      2     0%   5-7
libs/storage/artifact_storage.py             27     27     0%   13-197
libs/storage/interface.py                    27     27     0%   6-173
libs/storage/minio_storage.py               109    109     0%   6-431
libs/telemetry/__init__.py                    0      0   100%
libs/utils/__init__.py                        0      0   100%
... (18 more lines truncated)
```

## 2026-03-16T19:39:26Z  File: tests/unit/test_metadata_database_interface.py

```
============================= test session starts ==============================
collected 13 items

tests/unit/test_metadata_database_interface.py F...........F             [100%]

=================================== FAILURES ===================================
_ TestMetadataDatabaseConnection.test_database_connect_establishes_connection __
tests/unit/test_metadata_database_interface.py:27: in test_database_connect_establishes_connection
    assert mock_metadata_db.is_connected() is True, \
E   AssertionError: Database should be connected after successful connect()
E   assert <MagicMock name='mock.is_connected()' id='4449549728'> is True
E    +  where <MagicMock name='mock.is_connected()' id='4449549728'> = <MagicMock name='mock.is_connected' id='4449545888'>()
E    +    where <MagicMock name='mock.is_connected' id='4449545888'> = <MagicMock id='4448789488'>.is_connected
_ TestMetadataDatabaseQueryExecution.test_database_execute_logs_correlation_id _
tests/unit/test_metadata_database_interface.py:271: in test_database_execute_logs_correlation_id
    assert mock_logger.info.called or mock_logger.debug.called, \
E   AssertionError: Database should log queries with correlation_id
E   assert (False or False)
E    +  where False = <MagicMock name='mock.logger.info' id='4449511392'>.called
E    +    where <MagicMock name='mock.logger.info' id='4449511392'> = <MagicMock name='mock.logger' id='4449536144'>.info
E    +  and   False = <MagicMock name='mock.logger.debug' id='4449540176'>.called
E    +    where <MagicMock name='mock.logger.debug' id='4449540176'> = <MagicMock name='mock.logger' id='4449536144'>.debug
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      8     0%   2-13
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      6     0%   2-10
libs/contracts/errors.py                      5      5     0%   4-9
libs/contracts/health.py                     17     17     0%   2-27
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      2     0%   6-8
... (33 more lines truncated)
```
    wrote: tests/unit/conftest.py
    wrote: tests/unit/conftest.py
```
============================= test session starts ==============================
collected 13 items

tests/unit/test_metadata_database_interface.py ..........F..             [100%]

=================================== FAILURES ===================================
_ TestMetadataDatabaseQueryExecution.test_database_execute_query_returns_results _
tests/unit/test_metadata_database_interface.py:222: in test_database_execute_query_returns_results
    assert results == expected_results, "execute should return query results"
E   AssertionError: execute should return query results
E   assert [] == [{'id': 1, 'name': 'test'}]
E
E     Right contains one more item: {'id': 1, 'name': 'test'}
E     Use -v to get more diff
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      8     0%   2-13
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      6     0%   2-10
libs/contracts/errors.py                      5      5     0%   4-9
libs/contracts/health.py                     17     17     0%   2-27
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      2     0%   6-8
libs/db/metadata.py                          93     93     0%   7-326
libs/db/metadata_database.py                 51     51     0%   6-172
libs/feeds/__init__.py                        0      0   100%
libs/jobs/__init__.py                         0      0   100%
libs/parity/__init__.py                       0      0   100%
libs/quality/__init__.py                      0      0   100%
libs/storage/__init__.py                      2      2     0%   5-7
libs/storage/artifact_storage.py             27     27     0%   13-197
... (24 more lines truncated)
```
```
============================= test session starts ==============================
collected 41 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [ 29%]
tests/unit/test_artifact_storage_interface.py ................           [ 68%]
tests/unit/test_metadata_database_interface.py ..........F..             [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:164: in test_api_health_route_importable
    from services.api.main import app
E   ModuleNotFoundError: No module named 'services.api'
_ TestMetadataDatabaseQueryExecution.test_database_execute_query_returns_results _
tests/unit/test_metadata_database_interface.py:222: in test_database_execute_query_returns_results
    assert results == expected_results, "execute should return query results"
E   AssertionError: execute should return query results
E   assert [] == [{'id': 1, 'name': 'test'}]
E
E     Right contains one more item: {'id': 1, 'name': 'test'}
E     Use -v to get more diff
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
libs/audit/__init__.py                        0      0   100%
libs/authz/__init__.py                        0      0   100%
libs/contracts/__init__.py                    0      0   100%
libs/contracts/base.py                        8      0   100%
libs/contracts/config.py                     17     17     0%   3-52
libs/contracts/correlation.py                18     18     0%   3-36
libs/contracts/database.py                   29     29     0%   3-54
libs/contracts/enums.py                       6      0   100%
libs/contracts/errors.py                      5      3    40%   7-9
libs/contracts/health.py                     17     17     0%   2-27
libs/contracts/storage.py                    10     10     0%   6-140
libs/datasets/__init__.py                     0      0   100%
libs/db/__init__.py                           2      2     0%   6-8
libs/db/metadata.py                          93     93     0%   7-326
libs/db/metadata_database.py                 51     51     0%   6-172
... (29 more lines truncated)
```

## 2026-03-16T20:01:11Z  S4 M0 — targeting 2 file(s)


## 2026-03-16T20:01:11Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:166: in test_api_health_route_importable
    assert "/health" in routes
E   AssertionError: assert '/health' in {'/docs', '/docs/oauth2-redirect', '/openapi.json', '/redoc'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      0   100%
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      0   100%
libs/contracts/errors.py                        5      3    40%   7-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
libs/storage/__init__.py                        2      2     0%   5-7
libs/storage/artifact_storage.py               27     27     0%   13-197
libs/storage/interface.py                      27     27     0%   6-173
libs/storage/interfaces/__init__.py             0      0   100%
... (23 more lines truncated)
```
    wrote: services/api/routes/__init__.py
    wrote: services/api/routes/health.py
    wrote: services/api/app.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:166: in test_api_health_route_importable
    assert "/health" in routes
E   AssertionError: assert '/health' in {'/docs', '/docs/oauth2-redirect', '/openapi.json', '/redoc'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      0   100%
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      0   100%
libs/contracts/errors.py                        5      3    40%   7-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
libs/storage/__init__.py                        2      2     0%   5-7
libs/storage/artifact_storage.py               27     27     0%   13-197
libs/storage/interface.py                      27     27     0%   6-173
libs/storage/interfaces/__init__.py             0      0   100%
... (24 more lines truncated)
```

## 2026-03-16T20:01:24Z  File: tests/unit/test_metadata_database_interface.py

```
============================= test session starts ==============================
collected 13 items

tests/unit/test_metadata_database_interface.py ..........F..             [100%]

=================================== FAILURES ===================================
_ TestMetadataDatabaseQueryExecution.test_database_execute_query_returns_results _
tests/unit/test_metadata_database_interface.py:222: in test_database_execute_query_returns_results
    assert results == expected_results, "execute should return query results"
E   AssertionError: execute should return query results
E   assert [] == [{'id': 1, 'name': 'test'}]
E
E     Right contains one more item: {'id': 1, 'name': 'test'}
E     Use -v to get more diff
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      8     0%   2-13
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      6     0%   2-10
libs/contracts/errors.py                        5      5     0%   4-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
... (30 more lines truncated)
```
    wrote: tests/unit/conftest.py
    wrote: tests/unit/test_metadata_database_interface.py
    wrote: tests/unit/conftest.py
    wrote: tests/unit/conftest.py
```
============================= test session starts ==============================
collected 40 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [ 30%]
tests/unit/test_artifact_storage_interface.py ................           [ 70%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:166: in test_api_health_route_importable
    assert "/health" in routes
E   AssertionError: assert '/health' in {'/docs', '/docs/oauth2-redirect', '/openapi.json', '/redoc'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      0   100%
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      0   100%
libs/contracts/errors.py                        5      3    40%   7-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
libs/storage/__init__.py                        2      2     0%   5-7
libs/storage/artifact_storage.py               27     27     0%   13-197
... (26 more lines truncated)
```

## 2026-03-16T20:15:15Z  S4 M0 — targeting 1 file(s)


## 2026-03-16T20:15:15Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:166: in test_api_health_route_importable
    assert "/health" in routes
E   AssertionError: assert '/health' in {'/docs', '/docs/oauth2-redirect', '/openapi.json', '/redoc'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      0   100%
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      0   100%
libs/contracts/errors.py                        5      3    40%   7-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
libs/storage/__init__.py                        2      2     0%   5-7
libs/storage/artifact_storage.py               27     27     0%   13-197
libs/storage/interface.py                      27     27     0%   6-173
libs/storage/interfaces/__init__.py             0      0   100%
... (24 more lines truncated)
```

## 2026-03-16T20:31:12Z  S4 M0 — targeting 1 file(s)


## 2026-03-16T20:31:12Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:166: in test_api_health_route_importable
    assert "/health" in routes
E   AssertionError: assert '/health' in {'/docs', '/docs/oauth2-redirect', '/openapi.json', '/redoc'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      0   100%
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      0   100%
libs/contracts/errors.py                        5      3    40%   7-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
libs/storage/__init__.py                        2      2     0%   5-7
libs/storage/artifact_storage.py               27     27     0%   13-197
libs/storage/interface.py                      27     27     0%   6-173
libs/storage/interfaces/__init__.py             0      0   100%
... (24 more lines truncated)
```
    wrote: services/api/main.py
    wrote: services/api/main.py
    wrote: services/api/routes/health.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:167: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      0   100%
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      0   100%
libs/contracts/errors.py                        5      3    40%   7-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
libs/storage/__init__.py                        2      2     0%   5-7
libs/storage/artifact_storage.py               27     27     0%   13-197
libs/storage/interface.py                      27     27     0%   6-173
libs/storage/interfaces/__init__.py             0      0   100%
... (24 more lines truncated)
```
```
============================= test session starts ==============================
collected 40 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [ 30%]
tests/unit/test_artifact_storage_interface.py ................           [ 70%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:167: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      0   100%
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      0   100%
libs/contracts/errors.py                        5      3    40%   7-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
libs/storage/__init__.py                        2      2     0%   5-7
libs/storage/artifact_storage.py               27     27     0%   13-197
... (26 more lines truncated)
```

## 2026-03-16T21:50:28Z  S4 M0 — targeting 1 file(s)


## 2026-03-16T21:50:28Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:167: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc'}
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      0      0   100%
libs/contracts/base.py                          8      0   100%
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      0   100%
libs/contracts/errors.py                        5      3    40%   7-9
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/storage.py                      10     10     0%   6-140
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
libs/parity/__init__.py                         0      0   100%
libs/quality/__init__.py                        0      0   100%
libs/storage/__init__.py                        2      2     0%   5-7
libs/storage/artifact_storage.py               27     27     0%   13-197
libs/storage/interface.py                      27     27     0%   6-173
libs/storage/interfaces/__init__.py             0      0   100%
... (24 more lines truncated)
```
    wrote: services/api/routes/health.py
```
```
