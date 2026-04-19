from pathlib import Path
import tempfile
from src.orchestrator.bus import _atomic_write_text


def test_atomic_write_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    _atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_atomic_write_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    target.write_text("first")
    _atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"


def test_atomic_write_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "x.txt"
    _atomic_write_text(target, "deep")
    assert target.read_text(encoding="utf-8") == "deep"
