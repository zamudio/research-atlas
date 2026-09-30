"""Project/run creation and exact actual search inputs."""

from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.domain.execution import SearchExecution
from research_atlas.domain.studies import ResearchRun
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.serialization import json_value
from research_atlas.schemas.project_profile import ProjectProfile


async def create_project(engine: AsyncEngine, profile: ProjectProfile) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            s.projects.insert().values(
                project_id=profile.project_id,
                display_name=profile.display_name,
                context=profile.model_dump(mode="json", exclude={"project_id", "display_name"}),
            )
        )


async def create_research_run(engine: AsyncEngine, run: ResearchRun) -> None:
    json_value(run)  # Validate flexible values and timezone-aware timestamps before SQL.
    async with engine.begin() as conn:
        await conn.execute(s.research_runs.insert().values(**asdict(run)))


async def start_search_execution(engine: AsyncEngine, search: SearchExecution) -> None:
    if (
        search.status != "running"
        or search.checkpoint is not None
        or search.completed_batches
        or search.provider_result_count not in {None, 0}
        or search.completed_at is not None
        or search.requested_limit is None
    ):
        raise ValueError(
            "new searches must start running at the initial checkpoint with a batch limit"
        )
    json_value(search)
    values = asdict(search)
    values["parameters"] = json_value(search.parameters)
    values["provider_result_count"] = 0
    async with engine.begin() as conn:
        await conn.execute(s.search_executions.insert().values(**values))
