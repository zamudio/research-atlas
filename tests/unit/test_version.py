from pathlib import Path
from tomllib import load

from research_atlas import __version__


def test_package_version_matches_project_metadata() -> None:
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        project_version = load(pyproject_file)["project"]["version"]

    assert __version__ == project_version
