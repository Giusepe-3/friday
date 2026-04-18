import pytest


@pytest.fixture
def tmp_research(tmp_path):
    """Return a ResearchStorage rooted at a clean tmp dir."""
    from src.research.storage import ResearchStorage
    root = tmp_path / "research"
    return ResearchStorage(root)
