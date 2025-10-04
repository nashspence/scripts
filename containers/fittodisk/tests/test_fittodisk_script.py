import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import containers.fittodisk.script as script  # noqa: E402


def test_parse_size() -> None:
    assert script.parse_size("1") == 1
    assert script.parse_size("1k") == 1024
    assert script.parse_size("1.5m") == int(1.5 * 1024**2)
    assert script.parse_size("2g") == 2 * 1024**3
    assert script.parse_size("3t") == 3 * 1024**4


def _make_file(path: Path, size: int) -> None:
    path.write_bytes(b"0" * size)


def test_bundle_directories_copy(tmp_path: Path) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()

    files = [
        ("a.mkv", 1000),
        ("b.mkv", 2000),
        ("c.mkv", 3000),
    ]
    for name, size in files:
        _make_file(src / name, size)
    _make_file(src / ".job.json", 512)

    created = script.bundle_directories(str(src), str(out), 4096)
    assert created == ["01", "02"]

    first_dir = out / "01"
    second_dir = out / "02"
    assert first_dir.is_dir()
    assert second_dir.is_dir()

    copied = sorted(p.name for p in first_dir.iterdir()) + sorted(
        p.name for p in second_dir.iterdir()
    )
    assert copied == ["a.mkv", "b.mkv", "c.mkv"]

    for name, _size in files:
        assert (src / name).exists()
    assert (src / ".job.json").exists()
    assert not any(".job.json" in str(p) for p in out.rglob("*"))


def test_bundle_directories_move(tmp_path: Path) -> None:
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()

    _make_file(src / "clip1.mkv", 1024)
    _make_file(src / "clip2.mkv", 1024)

    created = script.bundle_directories(str(src), str(out), 1500, move=True)
    assert created == ["01", "02"]

    assert not any(src.iterdir())
    bundles = sorted(out.iterdir())
    assert [b.name for b in bundles] == ["01", "02"]
    assert sorted((bundles[0]).iterdir())[0].name.startswith("clip")
    assert sorted((bundles[1]).iterdir())[0].name.startswith("clip")
