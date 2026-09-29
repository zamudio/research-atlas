from dataclasses import replace
from datetime import UTC, datetime

import pytest

from research_atlas.domain.execution import SearchExecution, SearchParameter
from research_atlas.domain.studies import ResearchRun

NOW = datetime(2026, 9, 29, tzinfo=UTC)


def test_run_can_start_without_a_prescribed_search_plan() -> None:
    run = ResearchRun("run-1", "project-1", "What is supported?", "queued", NOW)
    assert run.plan == ()
    with pytest.raises(ValueError, match="started_at"):
        replace(run, status="running")
    with pytest.raises(ValueError, match="completed_at"):
        replace(run, status="completed")


def test_actual_execution_does_not_require_plan_approval() -> None:
    execution = SearchExecution(
        search_execution_id="search-1",
        run_id="run-1",
        provider_id="openalex",
        operation_id="openalex.search",
        exact_query=" a query\r\n",
        parameters=(SearchParameter("filter", "type:review"),),
        requested_limit=10,
        started_at=NOW,
        completed_at=NOW,
        status="succeeded",
        provider_result_count=0,
    )
    assert execution.exact_query == " a query\r\n"
    with pytest.raises(ValueError, match="provider_result_count"):
        replace(execution, provider_result_count=None)
    with pytest.raises(ValueError, match="error_type"):
        replace(execution, status="failed")
    with pytest.raises(ValueError, match="completed_at"):
        replace(execution, completed_at=None)
