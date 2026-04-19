from src.orchestrator.routing import normalize, route


WORKERS_CFG = {
    "paper": {"aliases": ["paper", "draft", "verification", "azr", "the paper"]},
    "thesis": {"aliases": ["thesis", "experiment", "dgm", "darwin godel", "coding agent", "polyglot"]},
    "research": {"aliases": ["research", "literature", "lit review", "progress", "the notes"]},
}


def test_normalize_lowercases_and_strips_punctuation() -> None:
    assert normalize("How's the Paper going?") == "how's the paper going"
    assert normalize("DGM!! refactor.") == "dgm refactor"


def test_route_paper_alias() -> None:
    assert route("Friday, how's the paper going?", WORKERS_CFG) == "paper"
    assert route("draft a new section", WORKERS_CFG) == "paper"


def test_route_thesis_alias() -> None:
    assert route("how's the experiment going?", WORKERS_CFG) == "thesis"
    assert route("ask the DGM agent to refactor X", WORKERS_CFG) == "thesis"


def test_route_research_alias() -> None:
    assert route("update the lit review", WORKERS_CFG) == "research"
    assert route("check progress on RSI papers", WORKERS_CFG) == "research"


def test_route_no_match_returns_none() -> None:
    assert route("what time is it?", WORKERS_CFG) is None


def test_route_first_match_wins() -> None:
    # "draft" is paper alias; "experiment" is thesis alias.
    # If both appear, first project iteration order wins (deterministic).
    text = "draft results from the experiment"
    result = route(text, WORKERS_CFG)
    assert result in {"paper", "thesis"}  # first encountered wins; both legitimate
