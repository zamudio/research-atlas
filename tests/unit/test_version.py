from pathlib import Path
from tomllib import load

from research_atlas import __version__

PYTHON_REQUIREMENT = ">=3.14,<3.15"
PYTHON_MINOR = "3.14"
PYTHON_PATCH = "3.14.7"


def test_package_version_matches_project_metadata() -> None:
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        project_version = load(pyproject_file)["project"]["version"]

    assert __version__ == project_version == "0.6.0"


def test_python_version_configuration_is_consistent() -> None:
    project_root = Path(__file__).parents[2]
    with (project_root / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = load(pyproject_file)

    assert pyproject["project"]["requires-python"] == PYTHON_REQUIREMENT
    assert pyproject["tool"]["pyright"]["pythonVersion"] == PYTHON_MINOR
    assert pyproject["tool"]["ruff"]["target-version"] == f"py{PYTHON_MINOR.replace('.', '')}"
    assert (project_root / ".python-version").read_text(encoding="utf-8").strip() == PYTHON_PATCH
