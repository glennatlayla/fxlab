
## 2026-03-17T18:12:21Z  M0 S3 RED baseline

Acceptance criteria (0):

RED failures S4 must fix:

```
============================= test session starts ==============================
collected 96 items

tests/acceptance/test_m0_bootstrap.py ....F.....F.                       [ 12%]
tests/unit/test_artifact_storage_interface.py ................           [ 29%]
tests/unit/test_m0_project_structure.py ..FFFFFFFF..FFFFFFFF.FFFFFFFF..F [ 62%]
FFFFFFFFFFF.....F...F...                                                 [ 87%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
______________________ test_active_workplan_is_valid_json ______________________
tests/acceptance/test_m0_bootstrap.py:72: in test_active_workplan_is_valid_json
    assert data["workplan_stem"] == "FXLab_Phase_1_workplan_v3"
E   AssertionError: assert 'FXLab_Phase_2_workplan_v2_1' == 'FXLab_Phase_1_workplan_v3'
E     
E     - FXLab_Phase_1_workplan_v3
E     ?             ^           ^
E     + FXLab_Phase_2_workplan_v2_1
E     ?             ^           ^^^
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:156: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
_____ TestAC1_DirectoryStructure.test_ac1_strategy_compiler_service_exists _____
tests/unit/test_m0_project_structure.py:36: in test_ac1_strategy_compiler_service_exists
    assert compiler_dir.exists(), "services/strategy_compiler/ directory must exist"
E   AssertionError: services/strategy_compiler/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/strategy_compiler').exists
______ TestAC1_DirectoryStructure.test_ac1_research_worker_service_exists ______
tests/unit/test_m0_project_structure.py:41: in test_ac1_research_worker_service_exists
    assert worker_dir.exists(), "services/research_worker/ directory must exist"
E   AssertionError: services/research_worker/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/research_worker').exists
____ TestAC1_DirectoryStructure.test_ac1_optimization_worker_service_exists ____
tests/unit/test_m0_project_structure.py:46: in test_ac1_optimization_worker_service_exists
    assert opt_dir.exists(), "services/optimization_worker/ directory must exist"
E   AssertionError: services/optimization_worker/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/optimization_worker').exists
_________ TestAC1_DirectoryStructure.test_ac1_readiness_service_exists _________
tests/unit/test_m0_project_structure.py:51: in test_ac1_readiness_service_exists
    assert readiness_dir.exists(), "services/readiness_service/ directory must exist"
E   AssertionError: services/readiness_service/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/readiness_service').exists
______ TestAC1_DirectoryStructure.test_ac1_libs_strategy_compiler_exists _______
tests/unit/test_m0_project_structure.py:56: in test_ac1_libs_strategy_compiler_exists
    assert lib_dir.exists(), "libs/strategy_compiler/ directory must exist"
E   AssertionError: libs/strategy_compiler/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('libs/strategy_compiler').exists
_________ TestAC1_DirectoryStructure.test_ac1_libs_strategy_ir_exists __________
tests/unit/test_m0_project_structure.py:61: in test_ac1_libs_strategy_ir_exists
    assert ir_dir.exists(), "libs/strategy_ir/ directory must exist"
E   AssertionError: libs/strategy_ir/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('libs/strategy_ir').exists
_______ TestAC1_DirectoryStructure.test_ac1_l
```

## 2026-03-17T18:13:56Z  S4 M0 — targeting 2 file(s)


## 2026-03-17T18:13:56Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ....F.....F.                       [100%]

=================================== FAILURES ===================================
______________________ test_active_workplan_is_valid_json ______________________
tests/acceptance/test_m0_bootstrap.py:72: in test_active_workplan_is_valid_json
    assert data["workplan_stem"] == "FXLab_Phase_1_workplan_v3"
E   AssertionError: assert 'FXLab_Phase_2_workplan_v2_1' == 'FXLab_Phase_1_workplan_v3'
E     
E     - FXLab_Phase_1_workplan_v3
E     ?             ^           ^
E     + FXLab_Phase_2_workplan_v2_1
E     ?             ^           ^^^
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:156: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
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
libs/contracts/export.py                       80     80     0%   4-130
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/optimization.py                106    106     0%   4-182
libs/contracts/readiness.py                    63     63     0%   4-107
libs/contracts/research.py                    128    128     0%   4-212
libs/contracts/storage.py                      10     10     0%   6-140
... (43 more lines truncated)
```
    wrote: docs/workplan-tracking/.active_workplan
    wrote: libs/contracts/__init__.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:156: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      2      2     0%   3-5
libs/contracts/base.py                          8      8     0%   2-13
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      6     0%   2-10
libs/contracts/errors.py                        5      5     0%   4-9
libs/contracts/export.py                       80     80     0%   4-130
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/optimization.py                106    106     0%   4-182
libs/contracts/readiness.py                    63     63     0%   4-107
libs/contracts/research.py                    128    128     0%   4-212
libs/contracts/storage.py                      10     10     0%   6-140
libs/contracts/strategy.py                    182    182     0%   4-308
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/feeds/__init__.py                          0      0   100%
libs/jobs/__init__.py                           0      0   100%
... (33 more lines truncated)
```

## 2026-03-17T18:14:11Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ..FFFFFFFF..FFFFFFFF.FFFFFFFF..F [ 57%]
FFFFFFFFFFF.....F...F...                                                 [100%]

=================================== FAILURES ===================================
_____ TestAC1_DirectoryStructure.test_ac1_strategy_compiler_service_exists _____
tests/unit/test_m0_project_structure.py:36: in test_ac1_strategy_compiler_service_exists
    assert compiler_dir.exists(), "services/strategy_compiler/ directory must exist"
E   AssertionError: services/strategy_compiler/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/strategy_compiler').exists
______ TestAC1_DirectoryStructure.test_ac1_research_worker_service_exists ______
tests/unit/test_m0_project_structure.py:41: in test_ac1_research_worker_service_exists
    assert worker_dir.exists(), "services/research_worker/ directory must exist"
E   AssertionError: services/research_worker/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/research_worker').exists
____ TestAC1_DirectoryStructure.test_ac1_optimization_worker_service_exists ____
tests/unit/test_m0_project_structure.py:46: in test_ac1_optimization_worker_service_exists
    assert opt_dir.exists(), "services/optimization_worker/ directory must exist"
E   AssertionError: services/optimization_worker/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/optimization_worker').exists
_________ TestAC1_DirectoryStructure.test_ac1_readiness_service_exists _________
tests/unit/test_m0_project_structure.py:51: in test_ac1_readiness_service_exists
    assert readiness_dir.exists(), "services/readiness_service/ directory must exist"
E   AssertionError: services/readiness_service/ directory must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/readiness_service').exists
______ TestAC1_DirectoryStructure.test_ac1_libs_strategy_compiler_exists _______
tests/unit/test_m0_project_structure.py:56: in test_ac1_libs_strategy_compiler_exists
    assert lib_dir.exists(), "libs/strategy_compiler/ directory must exist"
E   AssertionError: libs/strategy_compiler/ directory must exist
E   assert False
... (348 more lines truncated)
```
    wrote: services/strategy_compiler/__init__.py
    wrote: services/research_worker/__init__.py
    wrote: services/optimization_worker/__init__.py
    wrote: services/readiness_service/__init__.py
    wrote: libs/strategy_compiler/__init__.py
    wrote: libs/strategy_ir/__init__.py
    wrote: libs/experiment_plan/__init__.py
    wrote: libs/risk/__init__.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py .....................FFFFFFFF..F [ 57%]
FFF....FFFF.....F...F...                                                 [100%]

=================================== FAILURES ===================================
______ TestAC3_ServiceEntryPoints.test_ac3_strategy_compiler_main_exists _______
tests/unit/test_m0_project_structure.py:139: in test_ac3_strategy_compiler_main_exists
    assert main_file.exists(), "services/strategy_compiler/main.py must exist"
E   AssertionError: services/strategy_compiler/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/strategy_compiler/main.py').exists
_______ TestAC3_ServiceEntryPoints.test_ac3_research_worker_main_exists ________
tests/unit/test_m0_project_structure.py:144: in test_ac3_research_worker_main_exists
    assert main_file.exists(), "services/research_worker/main.py must exist"
E   AssertionError: services/research_worker/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/research_worker/main.py').exists
_____ TestAC3_ServiceEntryPoints.test_ac3_optimization_worker_main_exists ______
tests/unit/test_m0_project_structure.py:149: in test_ac3_optimization_worker_main_exists
    assert main_file.exists(), "services/optimization_worker/main.py must exist"
E   AssertionError: services/optimization_worker/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/optimization_worker/main.py').exists
______ TestAC3_ServiceEntryPoints.test_ac3_readiness_service_main_exists _______
tests/unit/test_m0_project_structure.py:154: in test_ac3_readiness_service_main_exists
    assert main_file.exists(), "services/readiness_service/main.py must exist"
E   AssertionError: services/readiness_service/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/readiness_service/main.py').exists
_____________ TestAC4_RouteFiles.test_ac4_strategies_route_exists ______________
tests/unit/test_m0_project_structure.py:163: in test_ac4_strategies_route_exists
    assert route_file.exists(), "services/api/routes/strategies.py must exist"
E   AssertionError: services/api/routes/strategies.py must exist
E   assert False
... (188 more lines truncated)
```
```
============================= test session starts ==============================
collected 96 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [ 12%]
tests/unit/test_artifact_storage_interface.py ................           [ 29%]
tests/unit/test_m0_project_structure.py .....................FFFFFFFF..F [ 62%]
FFF....FFFF.....F...F...                                                 [ 87%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:156: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
______ TestAC3_ServiceEntryPoints.test_ac3_strategy_compiler_main_exists _______
tests/unit/test_m0_project_structure.py:139: in test_ac3_strategy_compiler_main_exists
    assert main_file.exists(), "services/strategy_compiler/main.py must exist"
E   AssertionError: services/strategy_compiler/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/strategy_compiler/main.py').exists
_______ TestAC3_ServiceEntryPoints.test_ac3_research_worker_main_exists ________
tests/unit/test_m0_project_structure.py:144: in test_ac3_research_worker_main_exists
    assert main_file.exists(), "services/research_worker/main.py must exist"
E   AssertionError: services/research_worker/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/research_worker/main.py').exists
_____ TestAC3_ServiceEntryPoints.test_ac3_optimization_worker_main_exists ______
tests/unit/test_m0_project_structure.py:149: in test_ac3_optimization_worker_main_exists
    assert main_file.exists(), "services/optimization_worker/main.py must exist"
E   AssertionError: services/optimization_worker/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/optimization_worker/main.py').exists
______ TestAC3_ServiceEntryPoints.test_ac3_readiness_service_main_exists _______
tests/unit/test_m0_project_structure.py:154: in test_ac3_readiness_service_main_exists
    assert main_file.exists(), "services/readiness_service/main.py must exist"
E   AssertionError: services/readiness_service/main.py must exist
... (197 more lines truncated)
```

## 2026-03-17T18:17:01Z  S4 M0 — targeting 2 file(s)


## 2026-03-17T18:17:01Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ....F.....F.                       [100%]

=================================== FAILURES ===================================
______________________ test_active_workplan_is_valid_json ______________________
tests/acceptance/test_m0_bootstrap.py:72: in test_active_workplan_is_valid_json
    assert data["workplan_stem"] == "FXLab_Phase_1_workplan_v3"
E   AssertionError: assert 'FXLab_Phase_2_workplan_v2_1' == 'FXLab_Phase_1_workplan_v3'
E     
E     - FXLab_Phase_1_workplan_v3
E     ?             ^           ^
E     + FXLab_Phase_2_workplan_v2_1
E     ?             ^           ^^^
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:156: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      2      2     0%   3-5
libs/contracts/base.py                          8      8     0%   2-13
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      6     0%   2-10
libs/contracts/errors.py                        5      5     0%   4-9
libs/contracts/export.py                       80     80     0%   4-130
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/optimization.py                106    106     0%   4-182
libs/contracts/readiness.py                    63     63     0%   4-107
libs/contracts/research.py                    128    128     0%   4-212
libs/contracts/storage.py                      10     10     0%   6-140
... (51 more lines truncated)
```
    wrote: docs/workplan-tracking/.active_workplan
    wrote: libs/contracts/__init__.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:156: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                        Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------
libs/audit/__init__.py                          0      0   100%
libs/authz/__init__.py                          0      0   100%
libs/contracts/__init__.py                      2      2     0%   5-7
libs/contracts/base.py                          8      8     0%   2-13
libs/contracts/config.py                       17     17     0%   3-52
libs/contracts/correlation.py                  18     18     0%   3-36
libs/contracts/database.py                     29     29     0%   3-54
libs/contracts/enums.py                         6      6     0%   2-10
libs/contracts/errors.py                        5      5     0%   4-9
libs/contracts/export.py                       80     80     0%   4-130
libs/contracts/health.py                       17     17     0%   2-27
libs/contracts/optimization.py                106    106     0%   4-182
libs/contracts/readiness.py                    63     63     0%   4-107
libs/contracts/research.py                    128    128     0%   4-212
libs/contracts/storage.py                      10     10     0%   6-140
libs/contracts/strategy.py                    182    182     0%   4-308
libs/datasets/__init__.py                       0      0   100%
libs/db/__init__.py                             2      2     0%   6-8
libs/db/interfaces/__init__.py                  0      0   100%
libs/db/interfaces/connection_manager.py       11     11     0%   3-38
libs/db/metadata.py                            93     93     0%   7-326
libs/db/metadata_database.py                   51     51     0%   6-172
libs/experiment_plan/__init__.py                0      0   100%
libs/feeds/__init__.py                          0      0   100%
... (41 more lines truncated)
```

## 2026-03-17T18:17:15Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py .....................FFFFFFFF..F [ 57%]
FFF....FFFF.....F...F...                                                 [100%]

=================================== FAILURES ===================================
______ TestAC3_ServiceEntryPoints.test_ac3_strategy_compiler_main_exists _______
tests/unit/test_m0_project_structure.py:139: in test_ac3_strategy_compiler_main_exists
    assert main_file.exists(), "services/strategy_compiler/main.py must exist"
E   AssertionError: services/strategy_compiler/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/strategy_compiler/main.py').exists
_______ TestAC3_ServiceEntryPoints.test_ac3_research_worker_main_exists ________
tests/unit/test_m0_project_structure.py:144: in test_ac3_research_worker_main_exists
    assert main_file.exists(), "services/research_worker/main.py must exist"
E   AssertionError: services/research_worker/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/research_worker/main.py').exists
_____ TestAC3_ServiceEntryPoints.test_ac3_optimization_worker_main_exists ______
tests/unit/test_m0_project_structure.py:149: in test_ac3_optimization_worker_main_exists
    assert main_file.exists(), "services/optimization_worker/main.py must exist"
E   AssertionError: services/optimization_worker/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/optimization_worker/main.py').exists
______ TestAC3_ServiceEntryPoints.test_ac3_readiness_service_main_exists _______
tests/unit/test_m0_project_structure.py:154: in test_ac3_readiness_service_main_exists
    assert main_file.exists(), "services/readiness_service/main.py must exist"
E   AssertionError: services/readiness_service/main.py must exist
E   assert False
E    +  where False = exists()
E    +    where exists = PosixPath('services/readiness_service/main.py').exists
_____________ TestAC4_RouteFiles.test_ac4_strategies_route_exists ______________
tests/unit/test_m0_project_structure.py:163: in test_ac4_strategies_route_exists
    assert route_file.exists(), "services/api/routes/strategies.py must exist"
E   AssertionError: services/api/routes/strategies.py must exist
E   assert False
... (188 more lines truncated)
```
    wrote: services/strategy_compiler/main.py
    wrote: services/research_worker/main.py
    wrote: services/optimization_worker/main.py
    wrote: services/readiness_service/main.py
    wrote: services/api/routes/strategies.py
    wrote: services/api/routes/runs.py
    wrote: services/api/routes/readiness.py
    wrote: services/api/routes/exports.py
    wrote: libs/strategy_compiler/__init__.py
    wrote: libs/strategy_ir/__init__.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
FFF....FFFF.....F...F...                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
E   ModuleNotFoundError: No module named 'libs.strategy_compiler'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: No module named 'libs.strategy_compiler'
______ TestAC5_PackageImportability.test_ac5_libs_strategy_ir_importable _______
tests/unit/test_m0_project_structure.py:212: in test_ac5_libs_strategy_ir_importable
    import libs.strategy_ir
E   ModuleNotFoundError: No module named 'libs.strategy_ir'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:215: in test_ac5_libs_strategy_ir_importable
    pytest.fail(f"libs.strategy_ir must be importable: {e}")
E   Failed: libs.strategy_ir must be importable: No module named 'libs.strategy_ir'
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
E   ModuleNotFoundError: No module named 'libs.experiment_plan'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: No module named 'libs.experiment_plan'
__________ TestAC5_PackageImportability.test_ac5_libs_risk_importable __________
tests/unit/test_m0_project_structure.py:228: in test_ac5_libs_risk_importable
    import libs.risk
E   ModuleNotFoundError: No module named 'libs.risk'

During handling of the above exception, another exception occurred:
... (132 more lines truncated)
```
```
============================= test session starts ==============================
collected 96 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [ 12%]
tests/unit/test_artifact_storage_interface.py ................           [ 29%]
tests/unit/test_m0_project_structure.py ...............................F [ 62%]
FFF....FFFF.....F...F...                                                 [ 87%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:156: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
E   ModuleNotFoundError: No module named 'libs.strategy_compiler'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: No module named 'libs.strategy_compiler'
______ TestAC5_PackageImportability.test_ac5_libs_strategy_ir_importable _______
tests/unit/test_m0_project_structure.py:212: in test_ac5_libs_strategy_ir_importable
    import libs.strategy_ir
E   ModuleNotFoundError: No module named 'libs.strategy_ir'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:215: in test_ac5_libs_strategy_ir_importable
    pytest.fail(f"libs.strategy_ir must be importable: {e}")
E   Failed: libs.strategy_ir must be importable: No module named 'libs.strategy_ir'
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
E   ModuleNotFoundError: No module named 'libs.experiment_plan'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
... (141 more lines truncated)
```

## 2026-03-17T18:57:30Z  S4 M0 — targeting 2 file(s)


## 2026-03-17T18:57:30Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:169: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          2      2     0%   5-7
libs/contracts/base.py                              8      8     0%   2-13
libs/contracts/config.py                           17     17     0%   3-52
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      6     0%   2-10
libs/contracts/errors.py                            5      5     0%   4-9
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                        128    128     0%   4-212
libs/contracts/storage.py                          10     10     0%   6-140
libs/contracts/strategy.py                        182    182     0%   4-308
libs/datasets/__init__.py                           0      0   100%
libs/datasets/interfaces/__init__.py                0      0   100%
... (79 more lines truncated)
```
    wrote: libs/contracts/__init__.py
    wrote: libs/contracts/enums.py
    wrote: libs/contracts/base.py
    wrote: libs/contracts/errors.py
    wrote: tests/conftest.py
    wrote: libs/contracts/config.py
    wrote: libs/contracts/__init__.py
    wrote: libs/contracts/base.py
    wrote: libs/contracts/__init__.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:169: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          0      0   100%
libs/contracts/base.py                              9      9     0%   2-18
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      6     0%   2-10
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                        128    128     0%   4-212
libs/contracts/storage.py                          10     10     0%   6-140
libs/contracts/strategy.py                        182    182     0%   4-308
libs/datasets/__init__.py                           0      0   100%
libs/datasets/interfaces/__init__.py                0      0   100%
... (79 more lines truncated)
```

## 2026-03-17T18:58:28Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
FFF.............F.......                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
E   ModuleNotFoundError: No module named 'libs.strategy_compiler'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: No module named 'libs.strategy_compiler'
______ TestAC5_PackageImportability.test_ac5_libs_strategy_ir_importable _______
tests/unit/test_m0_project_structure.py:212: in test_ac5_libs_strategy_ir_importable
    import libs.strategy_ir
E   ModuleNotFoundError: No module named 'libs.strategy_ir'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:215: in test_ac5_libs_strategy_ir_importable
    pytest.fail(f"libs.strategy_ir must be importable: {e}")
E   Failed: libs.strategy_ir must be importable: No module named 'libs.strategy_ir'
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
E   ModuleNotFoundError: No module named 'libs.experiment_plan'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: No module named 'libs.experiment_plan'
__________ TestAC5_PackageImportability.test_ac5_libs_risk_importable __________
tests/unit/test_m0_project_structure.py:228: in test_ac5_libs_risk_importable
    import libs.risk
E   ModuleNotFoundError: No module named 'libs.risk'

During handling of the above exception, another exception occurred:
... (122 more lines truncated)
```
    wrote: libs/strategy_compiler/__init__.py
    wrote: libs/strategy_ir/__init__.py
    wrote: libs/experiment_plan/__init__.py
    wrote: libs/risk/__init__.py
    wrote: services/api/main.py
    wrote: libs/strategy_compiler/interfaces/__init__.py
    wrote: libs/strategy_ir/interfaces/__init__.py
    wrote: libs/experiment_plan/interfaces/__init__.py
    wrote: libs/risk/interfaces/__init__.py
    wrote: libs/strategy_compiler/mocks/__init__.py
    wrote: libs/strategy_ir/mocks/__init__.py
    wrote: libs/experiment_plan/mocks/__init__.py
    wrote: libs/risk/mocks/__init__.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
FFF.............F.......                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
E   ModuleNotFoundError: No module named 'libs.strategy_compiler'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: No module named 'libs.strategy_compiler'
______ TestAC5_PackageImportability.test_ac5_libs_strategy_ir_importable _______
tests/unit/test_m0_project_structure.py:212: in test_ac5_libs_strategy_ir_importable
    import libs.strategy_ir
E   ModuleNotFoundError: No module named 'libs.strategy_ir'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:215: in test_ac5_libs_strategy_ir_importable
    pytest.fail(f"libs.strategy_ir must be importable: {e}")
E   Failed: libs.strategy_ir must be importable: No module named 'libs.strategy_ir'
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
E   ModuleNotFoundError: No module named 'libs.experiment_plan'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: No module named 'libs.experiment_plan'
__________ TestAC5_PackageImportability.test_ac5_libs_risk_importable __________
tests/unit/test_m0_project_structure.py:228: in test_ac5_libs_risk_importable
    import libs.risk
E   ModuleNotFoundError: No module named 'libs.risk'

During handling of the above exception, another exception occurred:
... (122 more lines truncated)
```
```
============================= test session starts ==============================
collected 96 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [ 12%]
tests/unit/test_artifact_storage_interface.py ................           [ 29%]
tests/unit/test_m0_project_structure.py ...............................F [ 62%]
FFF.............F.......                                                 [ 87%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:169: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
E   ModuleNotFoundError: No module named 'libs.strategy_compiler'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: No module named 'libs.strategy_compiler'
______ TestAC5_PackageImportability.test_ac5_libs_strategy_ir_importable _______
tests/unit/test_m0_project_structure.py:212: in test_ac5_libs_strategy_ir_importable
    import libs.strategy_ir
E   ModuleNotFoundError: No module named 'libs.strategy_ir'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:215: in test_ac5_libs_strategy_ir_importable
    pytest.fail(f"libs.strategy_ir must be importable: {e}")
E   Failed: libs.strategy_ir must be importable: No module named 'libs.strategy_ir'
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
E   ModuleNotFoundError: No module named 'libs.experiment_plan'

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
... (131 more lines truncated)
```

## 2026-03-17T19:17:30Z  S4 M0 — round 1/3, 2 file(s)


## 2026-03-17T19:17:30Z  File: tests/acceptance/test_m0_bootstrap.py

```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:169: in test_contracts_importable
    from libs.contracts import enums, base, errors  # noqa: F401
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ModuleNotFoundError: No module named 'libs.contracts'
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
libs/authz/interfaces/__init__.py                   0      0   100%
libs/authz/mocks/__init__.py                        0      0   100%
libs/contracts/__init__.py                          0      0   100%
libs/contracts/base.py                              9      9     0%   2-18
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      6     0%   2-10
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                        128    128     0%   4-212
libs/contracts/storage.py                          10     10     0%   6-140
libs/contracts/strategy.py                        182    182     0%   4-308
libs/datasets/__init__.py                           0      0   100%
libs/datasets/interfaces/__init__.py                0      0   100%
... (79 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: libs/__init__.py
    wrote: tests/__init__.py
    wrote: tests/acceptance/__init__.py
    wrote: libs/contracts/__init__.py
    wrote: pytest.ini
    wrote: conftest.py
    retry 1 for tests/acceptance/test_m0_bootstrap.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ..........F.                       [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             6      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                        128    128     0%   4-212
libs/contracts/storage.py                          10     10     0%   6-140
libs/contracts/strategy.py                        182    182     0%   4-308
libs/datasets/__init__.py                           0      0   100%
... (81 more lines truncated)
```
    wrote (retry 1): libs/contracts/enums.py

## 2026-03-17T19:18:09Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F..............F.......                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:3: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:6: in <module>
    from libs.contracts.strategy import StrategyDefinition
E   ImportError: cannot import name 'StrategyDefinition' from 'libs.contracts.strategy' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/strategy.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: cannot import name 'StrategyDefinition' from 'libs.contracts.strategy' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/strategy.py)
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:3: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:6: in <module>
    from libs.contracts.research import ExperimentPlan
E   ImportError: cannot import name 'ExperimentPlan' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ExperimentPlan' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
E   AssertionError: services/api/app.py must NOT exist - use main.py
E   assert not True
... (114 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: libs/contracts/strategy.py
    wrote: libs/contracts/research.py
    wrote: libs/contracts/enums.py
    wrote: libs/strategy_compiler/interfaces/__init__.py
    wrote: libs/experiment_plan/interfaces/__init__.py
    wrote: services/api/main.py
    wrote: services/__init__.py
    wrote: services/api/__init__.py
    wrote: services/api/routes/__init__.py
    wrote: services/strategy_compiler/__init__.py
    wrote: services/research_worker/__init__.py
    wrote: services/optimization_worker/__init__.py
    wrote: services/readiness_service/__init__.py
    wrote: libs/strategy_compiler/__init__.py
    wrote: libs/strategy_compiler/mocks/__init__.py
    wrote: libs/strategy_ir/__init__.py
    wrote: libs/strategy_ir/interfaces/__init__.py
    wrote: libs/strategy_ir/mocks/__init__.py
    wrote: libs/experiment_plan/__init__.py
    wrote: libs/experiment_plan/mocks/__init__.py
    wrote: libs/risk/__init__.py
    wrote: libs/risk/interfaces/__init__.py
    wrote: libs/risk/mocks/__init__.py
    retry 1 for tests/unit/test_m0_project_structure.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ................................ [ 57%]
................F.......                                                 [100%]

=================================== FAILURES ===================================
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
E   AssertionError: services/api/app.py must NOT exist - use main.py
E   assert not True
E    +  where True = exists()
E    +    where exists = PosixPath('services/api/app.py').exists
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            11      0   100%
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                         37      0   100%
... (84 more lines truncated)
```
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ................................ [ 57%]
................F.......                                                 [100%]

=================================== FAILURES ===================================
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
E   AssertionError: services/api/app.py must NOT exist - use main.py
E   assert not True
E    +  where True = exists()
E    +    where exists = PosixPath('services/api/app.py').exists
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            11      0   100%
libs/contracts/errors.py                            6      6     0%   4-16
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                         37      0   100%
... (84 more lines truncated)
```
```
============================= test session starts ==============================
collected 96 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [ 12%]
tests/unit/test_artifact_storage_interface.py ................           [ 29%]
tests/unit/test_m0_project_structure.py ................................ [ 62%]
................F.......                                                 [ 87%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:179: in test_api_health_route_importable
    assert "/health" in routes
E   AssertionError: assert '/health' in {'/docs', '/docs/oauth2-redirect', '/openapi.json', '/redoc'}
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
E   AssertionError: services/api/app.py must NOT exist - use main.py
E   assert not True
E    +  where True = exists()
E    +    where exists = PosixPath('services/api/app.py').exists
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
libs/contracts/base.py                              9      0   100%
... (98 more lines truncated)
```

## 2026-03-17T19:19:03Z  S4 M0 — round 2/3, 2 file(s)


## 2026-03-17T19:19:03Z  File: tests/acceptance/test_m0_bootstrap.py

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
tests/acceptance/test_m0_bootstrap.py:179: in test_api_health_route_importable
    assert "/health" in routes
E   AssertionError: assert '/health' in {'/docs', '/docs/oauth2-redirect', '/openapi.json', '/redoc'}
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            11      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
... (86 more lines truncated)
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
services/api/main.py:5: in <module>
    from services.api.routes import health
services/api/routes/health.py:3: in <module>
    from libs.contracts.health import HealthCheckResponse, ServiceStatus
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             5      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17      0   100%
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                         37     37     0%   2-70
... (84 more lines truncated)
```
    wrote (retry 1): services/api/routes/health.py
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:179: in test_api_health_route_importable
    assert "/health" in routes
E   AssertionError: assert '/health' in {'/docs', '/docs/oauth2-redirect', '/health/', '/openapi.json', '/redoc'}
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                             5      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                         37     37     0%   2-70
libs/contracts/storage.py                          10     10     0%   6-140
libs/contracts/strategy.py                         28     28     0%   2-53
libs/datasets/__init__.py                           0      0   100%
libs/datasets/interfaces/__init__.py                0      0   100%
... (80 more lines truncated)
```

## 2026-03-17T19:19:28Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F..............F.......                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:2: in <module>
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
libs/experiment_plan/__init__.py:2: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:4: in <module>
    from libs.contracts.research import ExperimentPlan, ResearchRun
libs/contracts/research.py:8: in <module>
    from libs.contracts.enums import ResearchPhase
E   ImportError: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
... (118 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: libs/contracts/enums.py
    wrote: services/api/main.py
    wrote: services/api/__init__.py
    wrote: services/api/routes/__init__.py
    wrote: services/strategy_compiler/__init__.py
    wrote: services/strategy_compiler/main.py
    wrote: services/research_worker/__init__.py
    wrote: services/research_worker/main.py
    wrote: services/optimization_worker/__init__.py
    wrote: services/optimization_worker/main.py
    wrote: services/readiness_service/__init__.py
    wrote: services/readiness_service/main.py
    wrote: libs/strategy_compiler/__init__.py
    wrote: libs/strategy_compiler/interfaces/__init__.py
    wrote: libs/strategy_compiler/mocks/__init__.py
    wrote: libs/strategy_ir/__init__.py
    wrote: libs/strategy_ir/interfaces/__init__.py
    wrote: libs/strategy_ir/mocks/__init__.py
    wrote: libs/experiment_plan/__init__.py
    wrote: libs/experiment_plan/interfaces/__init__.py
    wrote: libs/experiment_plan/mocks/__init__.py
    wrote: libs/risk/__init__.py
    wrote: libs/risk/interfaces/__init__.py
    wrote: libs/risk/mocks/__init__.py
    retry 1 for tests/unit/test_m0_project_structure.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ................................ [ 57%]
.F..............F.......                                                 [100%]

=================================== FAILURES ===================================
____ TestAC5_PackageImportability.test_ac5_libs_experiment_plan_importable _____
tests/unit/test_m0_project_structure.py:220: in test_ac5_libs_experiment_plan_importable
    import libs.experiment_plan
libs/experiment_plan/__init__.py:2: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:3: in <module>
    from libs.contracts.research import ExperimentPlan
libs/contracts/research.py:8: in <module>
    from libs.contracts.enums import ResearchPhase
E   ImportError: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
E   AssertionError: services/api/app.py must NOT exist - use main.py
E   assert not True
E    +  where True = exists()
E    +    where exists = PosixPath('services/api/app.py').exists
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
... (101 more lines truncated)
```
    wrote (retry 1): libs/contracts/enums.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
................F.......                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:2: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:3: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:8: in <module>
    from libs.contracts.enums import StrategyType
E   ImportError: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
E   AssertionError: services/api/app.py must NOT exist - use main.py
E   assert not True
E    +  where True = exists()
E    +    where exists = PosixPath('services/api/app.py').exists
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
... (101 more lines truncated)
```
```
============================= test session starts ==============================
collected 96 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [ 12%]
tests/unit/test_artifact_storage_interface.py ................           [ 29%]
tests/unit/test_m0_project_structure.py ...............................F [ 62%]
................F.......                                                 [ 87%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc'}
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:2: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:3: in <module>
    from libs.contracts.strategy import StrategyDefinition, CompiledStrategy
libs/contracts/strategy.py:8: in <module>
    from libs.contracts.enums import StrategyType
E   ImportError: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:207: in test_ac5_libs_strategy_compiler_importable
    pytest.fail(f"libs.strategy_compiler must be importable: {e}")
E   Failed: libs.strategy_compiler must be importable: cannot import name 'StrategyType' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
E   AssertionError: services/api/app.py must NOT exist - use main.py
E   assert not True
... (115 more lines truncated)
```

## 2026-03-17T19:20:11Z  S4 M0 — round 3/3, 2 file(s)


## 2026-03-17T19:20:11Z  File: tests/acceptance/test_m0_bootstrap.py

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
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc'}
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            11      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           17     17     0%   2-27
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
... (86 more lines truncated)
```
    wrote: libs/contracts/enums.py
    wrote: services/api/routes/health.py
    wrote: services/api/main.py
    wrote: libs/contracts/health.py
    retry 1 for tests/acceptance/test_m0_bootstrap.py
```
============================= test session starts ==============================
collected 12 items

tests/acceptance/test_m0_bootstrap.py ...........F                       [100%]

=================================== FAILURES ===================================
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:177: in test_api_health_route_importable
    from services.api.main import app
services/api/main.py:7: in <module>
    from libs.contracts.correlation import correlation_middleware
E   ImportError: cannot import name 'correlation_middleware' from 'libs.contracts.correlation' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/correlation.py)
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18      6    67%   26-28, 34-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            11      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           10     10     0%   5-20
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                         37     37     0%   2-70
libs/contracts/storage.py                          10     10     0%   6-140
libs/contracts/strategy.py                         28     28     0%   2-53
... (82 more lines truncated)
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
services/api/main.py:6: in <module>
    from libs.contracts.health import HealthResponse
E   ImportError: cannot import name 'HealthResponse' from 'libs.contracts.health' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/health.py)
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            11      0   100%
libs/contracts/errors.py                            6      0   100%
libs/contracts/export.py                           80     80     0%   4-130
libs/contracts/health.py                           10      0   100%
libs/contracts/interfaces/__init__.py               0      0   100%
libs/contracts/mocks/__init__.py                    0      0   100%
libs/contracts/optimization.py                    106    106     0%   4-182
libs/contracts/readiness.py                        63     63     0%   4-107
libs/contracts/research.py                         37     37     0%   2-70
libs/contracts/storage.py                          10     10     0%   6-140
libs/contracts/strategy.py                         28     28     0%   2-53
... (82 more lines truncated)
```

## 2026-03-17T19:20:47Z  File: tests/unit/test_m0_project_structure.py

```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F..............F.......                                                 [100%]

=================================== FAILURES ===================================
___ TestAC5_PackageImportability.test_ac5_libs_strategy_compiler_importable ____
tests/unit/test_m0_project_structure.py:204: in test_ac5_libs_strategy_compiler_importable
    import libs.strategy_compiler
libs/strategy_compiler/__init__.py:2: in <module>
    from libs.strategy_compiler.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/strategy_compiler/interfaces/__init__.py:3: in <module>
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
libs/experiment_plan/__init__.py:2: in <module>
    from libs.experiment_plan.interfaces import *  # noqa: F401, F403
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
libs/experiment_plan/interfaces/__init__.py:3: in <module>
    from libs.contracts.research import ExperimentPlan
libs/contracts/research.py:8: in <module>
    from libs.contracts.enums import ResearchPhase
E   ImportError: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ResearchPhase' from 'libs.contracts.enums' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py)
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
... (118 more lines truncated)
```
    structural fix partial — escalating to LLM
    wrote: libs/contracts/enums.py
    wrote: services/api/main.py
    wrote: libs/strategy_compiler/__init__.py
    wrote: libs/strategy_compiler/interfaces/__init__.py
    wrote: libs/strategy_compiler/mocks/__init__.py
    wrote: libs/experiment_plan/__init__.py
    wrote: libs/experiment_plan/interfaces/__init__.py
    wrote: libs/experiment_plan/mocks/__init__.py
    retry 1 for tests/unit/test_m0_project_structure.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ................................ [ 57%]
.F..............F.......                                                 [100%]

=================================== FAILURES ===================================
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
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
E   AssertionError: services/api/app.py must NOT exist - use main.py
E   assert not True
E    +  where True = exists()
E    +    where exists = PosixPath('services/api/app.py').exists
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.13-final-0 _______________

Name                                            Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------------
libs/__init__.py                                    0      0   100%
libs/audit/__init__.py                              0      0   100%
libs/audit/interfaces/__init__.py                   0      0   100%
libs/audit/mocks/__init__.py                        0      0   100%
libs/authz/__init__.py                              0      0   100%
... (101 more lines truncated)
```
    wrote (retry 1): libs/contracts/enums.py
    wrote (retry 1): services/api/main.py
    wrote (retry 1): services/api/main.py
```
============================= test session starts ==============================
collected 56 items

tests/unit/test_m0_project_structure.py ...............................F [ 57%]
.F..............F.......                                                 [100%]

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
E   ImportError: cannot import name 'ExperimentDefinition' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ExperimentDefinition' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)
___________ TestAC8_NoPhase1Violations.test_ac8_api_not_named_app_py ___________
tests/unit/test_m0_project_structure.py:337: in test_ac8_api_not_named_app_py
    assert not app_file.exists(), "services/api/app.py must NOT exist - use main.py"
... (116 more lines truncated)
```
```
============================= test session starts ==============================
collected 96 items

tests/acceptance/test_m0_bootstrap.py ..........FF                       [ 12%]
tests/unit/test_artifact_storage_interface.py ................           [ 29%]
tests/unit/test_m0_project_structure.py ...............................F [ 62%]
.F..............F.......                                                 [ 87%]
tests/unit/test_metadata_database_interface.py ............              [100%]

=================================== FAILURES ===================================
__________________________ test_contracts_importable ___________________________
tests/acceptance/test_m0_bootstrap.py:170: in test_contracts_importable
    assert hasattr(enums, "FeedLifecycleStatus")
E   AssertionError: assert False
E    +  where False = hasattr(<module 'libs.contracts.enums' from '/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/enums.py'>, 'FeedLifecycleStatus')
_______________________ test_api_health_route_importable _______________________
tests/acceptance/test_m0_bootstrap.py:180: in test_api_health_route_importable
    assert "/health/dependencies" in routes
E   AssertionError: assert '/health/dependencies' in {'/docs', '/docs/oauth2-redirect', '/health', '/openapi.json', '/redoc'}
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
... (130 more lines truncated)
```

## 2026-03-17T21:11:38Z  S4 M0 — round 1/3, 1 file(s)


## 2026-03-17T21:11:38Z  File: tests/unit/test_m0_project_structure.py

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
libs/experiment_plan/interfaces/__init__.py:4: in <module>
    from libs.contracts.research import ExperimentDefinition, ExperimentPlan
E   ImportError: cannot import name 'ExperimentDefinition' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)

During handling of the above exception, another exception occurred:
tests/unit/test_m0_project_structure.py:223: in test_ac5_libs_experiment_plan_importable
    pytest.fail(f"libs.experiment_plan must be importable: {e}")
E   Failed: libs.experiment_plan must be importable: cannot import name 'ExperimentDefinition' from 'libs.contracts.research' (/Users/gjohnson/Documents/Coding Projects/fxlab/libs/contracts/research.py)
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
libs/contracts/base.py                              9      0   100%
libs/contracts/config.py                           23     23     0%   2-36
libs/contracts/correlation.py                      18     18     0%   3-36
libs/contracts/database.py                         29     29     0%   3-54
libs/contracts/enums.py                            40      0   100%
libs/contracts/errors.py                            6      6     0%   4-16
... (90 more lines truncated)
```
    wrote: libs/contracts/research.py
```
```
