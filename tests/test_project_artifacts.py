"""Submission artifacts for M5/M6 stay present and useful."""

from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_submission_artifacts_exist():
    for path in [
        "README.md",
        "Dockerfile",
        "threat_model.md",
        ".semgrep/rules.yaml",
        ".pre-commit-config.yaml",
    ]:
        assert (ROOT / path).exists(), path


def test_readme_documents_safety_and_running():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "not investment advice" in readme.lower()
    assert "uv run uvicorn server.main:app" in readme
    assert "Cloud Run" in readme


def test_dockerfile_serves_fastapi_app():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "uvicorn server.main:app" in dockerfile
    assert "frontend/dist" in dockerfile

