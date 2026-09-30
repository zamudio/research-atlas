from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid7

import pytest

from research_atlas.domain.execution import RunSource, SearchExecution, SearchParameter
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


def test_partial_execution_retains_progress_and_checkpoint_without_requiring_failure() -> None:
    execution = SearchExecution(
        "search-1",
        "run-1",
        "openalex",
        "openalex.search",
        "exact query",
        (),
        100,
        NOW,
        NOW,
        "partial",
        provider_result_count=200,
        checkpoint="opaque-next-page",
        completed_batches=2,
    )
    assert execution.error_type is None
    with pytest.raises(ValueError, match="checkpoint"):
        replace(execution, checkpoint=None)
    with pytest.raises(ValueError, match="continuation"):
        replace(execution, status="succeeded")
    assert (
        replace(execution, status="running", completed_at=None).checkpoint == execution.checkpoint
    )


def test_run_source_progress_distinguishes_processing_coverage_from_search_success() -> None:
    memberships = (
        RunSource("run-1", uuid7()),
        RunSource("run-1", uuid7(), processing_state="retrieved"),
        RunSource("run-1", uuid7(), selected_extraction_id=uuid7(), processing_state="extracted"),
        RunSource("run-1", uuid7(), processing_state="excluded"),
        RunSource("run-1", uuid7(), processing_state="unavailable"),
        RunSource("run-1", uuid7(), processing_state="failed"),
    )
    search = SearchExecution(
        "search-1",
        "run-1",
        "crossref",
        "crossref.works",
        "q",
        (),
        100,
        NOW,
        NOW,
        "succeeded",
        provider_result_count=6,
        completed_batches=1,
    )
    assert search.status == "succeeded"
    assert Counter(item.processing_state for item in memberships) == {
        "discovered": 1,
        "retrieved": 1,
        "extracted": 1,
        "excluded": 1,
        "unavailable": 1,
        "failed": 1,
    }
    # The same Source can have different current outcomes in different runs.
    other_run = RunSource("run-2", memberships[-1].source_id)
    assert other_run.processing_state == "discovered"
    assert memberships[-1].processing_state == "failed"
