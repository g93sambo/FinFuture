## 2026-10-11T09:47:16Z
You are the Remediation Worker for Milestone 4 (Compliance, Execution & Health Report) of the Wealth Advisory Agent backend.
Your working directory is: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m4_remed
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md

Write Ownership:
You own exclusively:
- backend/tests/unit/test_health_report.py

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context & Issue:
In Milestone 4 Gate review, `test_health_report.py::test_narrative_openai_mode` failed when run with pytest:
`AssertionError: assert 'DETERMINISTIC_FALLBACK' == 'LLM_OPENAI'`
Root Cause:
In `backend/tests/conftest.py:14`, `os.environ["DRY_RUN"] = "true"` is set to isolate testing.
In `backend/services/health_report.py:824`, the narrative generator checks:
`if HAS_OPENAI and self.openai_api_key and not getattr(settings, "dry_run", False):`
Because `settings.dry_run` is True under pytest, `generate_narrative` defaults to `_generate_deterministic_narrative` which returns `generation_mode = "DETERMINISTIC_FALLBACK"`.
In `backend/tests/unit/test_health_report.py:385-420`, `test_narrative_openai_mode` is designed to test that when `AsyncOpenAI` is mocked, the OpenAI code path is exercised and returns `generation_mode == "LLM_OPENAI"`.

Tasks:
1. In `backend/tests/unit/test_health_report.py`, update `test_narrative_openai_mode`:
   Patch `settings.dry_run` to `False` within the test context:
   ```python
   with patch("services.health_report.settings.dry_run", False):
       with patch("services.health_report.AsyncOpenAI") as mock_openai_cls:
           ...
   ```
   (or `with patch.object(settings, "dry_run", False):` with appropriate import).
2. Run test verification:
   - cd c:\Users\HP VICTUS\Documents\wealth_agent\backend
   - pytest -v tests/unit/test_health_report.py (all 17 tests must pass)
   - pytest -v tests/unit/test_compliance_guard.py tests/unit/test_execution_module.py tests/unit/test_health_report.py (all 66 tests must pass)
   - pytest -q (all 400 full suite tests must pass)
   - pytest -q --cov=agents.compliance_guard --cov=agents.execution_module --cov=services.health_report (verify >= 80% coverage)
3. Write your handoff report to `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m4_remed\handoff.md`.
4. Send a message to the orchestrator with your results and test outputs.
