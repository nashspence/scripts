"""Tests for mkiso script."""

import sys
import types
from pathlib import Path
from typing import Any, cast

fake_pycdlib = cast(Any, types.ModuleType("pycdlib"))


class _StubPyCdlib:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("pycdlib stub")


fake_pycdlib.PyCdlib = _StubPyCdlib
fake_pycdlibexception = cast(Any, types.ModuleType("pycdlib.pycdlibexception"))


class _StubPyCdlibException(Exception):
    pass


fake_pycdlibexception.PyCdlibException = _StubPyCdlibException
sys.modules.setdefault("pycdlib", fake_pycdlib)
sys.modules.setdefault("pycdlib.pycdlibexception", fake_pycdlibexception)

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import containers.mkiso.script as script  # noqa: E402


def test_stdout_is_output_filename(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("hi")
    out_dir = tmp_path / "out"
    argv = [
        "script.py",
        "--src-dir",
        str(src_dir),
        "--out-dir",
        str(out_dir),
        "--out-file",
        "foo.iso",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    called: dict[str, Any] = {}

    def fake_run(src: str, lbl: str, out: str, size: int, media: str) -> None:
        called.update(
            {
                "src": src,
                "label": lbl,
                "out": out,
                "size": size,
                "media": media,
            }
        )

    monkeypatch.setattr(script, "build_udf_image", fake_run)
    script.main()
    captured = capsys.readouterr()
    assert captured.out.strip() == "foo.iso"
    assert called["media"] == "bdr"


def test_media_type_passthrough(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    src_dir = tmp_path / "src2"
    src_dir.mkdir()
    (src_dir / "file.bin").write_text("data")
    out_dir = tmp_path / "out2"
    argv = [
        "script.py",
        "--src-dir",
        str(src_dir),
        "--out-dir",
        str(out_dir),
        "--out-file",
        "bar.iso",
        "--media-type",
        "cdr",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    recorded: dict[str, Any] = {}

    def fake_run(src: str, lbl: str, out: str, size: int, media: str) -> None:
        recorded["media"] = media

    monkeypatch.setattr(script, "build_udf_image", fake_run)
    script.main()
    captured = capsys.readouterr()
    assert captured.out.strip() == "bar.iso"
    assert recorded["media"] == "cdr"


def test_build_udf_image_creates_udf_tree(tmp_path: Path, monkeypatch: Any) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "data.bin").write_bytes(b"payload")
    (src_dir / "folder").mkdir()
    (src_dir / "folder" / "nested.txt").write_text("nested")
    (src_dir / "link").symlink_to("folder/nested.txt")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out_path = out_dir / "disk.iso"

    added_dirs: list[str] = []
    added_files: list[tuple[str, str, bytes]] = []
    added_links: list[tuple[str, str]] = []

    class FakeIso:
        def __init__(self) -> None:
            self.closed = False
            self.vol_ident: str | None = None
            self.udf_rev: str | None = None

        def new(self, *, vol_ident: str, udf: str) -> None:
            self.vol_ident = vol_ident
            self.udf_rev = udf

        def add_directory(self, udf_path: str, **_: Any) -> None:
            added_dirs.append(udf_path)

        def add_fp(
            self, fp: Any, length: int, iso_path: str, *, udf_path: str, **__: Any
        ) -> None:
            added_files.append((iso_path, udf_path, fp.read()))
            assert length == len(added_files[-1][2])

        def add_symlink(
            self, *, udf_symlink_path: str, udf_target: str, **_: Any
        ) -> None:
            added_links.append((udf_symlink_path, udf_target))

        def write(self, path: str) -> None:
            Path(path).write_bytes(b"iso")

        def close(self) -> None:
            self.closed = True

    fake_iso_instances: list[FakeIso] = []

    def fake_pycdlib() -> FakeIso:
        inst = FakeIso()
        fake_iso_instances.append(inst)
        return inst

    monkeypatch.setattr(script, "PyCdlib", fake_pycdlib)

    script.build_udf_image(str(src_dir), "Label 01", str(out_path), 1024, "bdr")

    assert out_path.exists()
    assert out_path.read_bytes() == b"iso"
    assert not (out_path.parent / "disk.iso.tmp").exists()

    assert fake_iso_instances and fake_iso_instances[0].closed is True
    assert fake_iso_instances[0].udf_rev == "2.01"
    assert fake_iso_instances[0].vol_ident == script.sanitize_volume_ident("Label 01")

    assert "/folder" in added_dirs
    assert any(udf == "/folder/nested.txt" for _, udf, _ in added_files)
    assert any(link == "/link" for link, _ in added_links)
