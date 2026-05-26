"""Unit tests for the path-validation helpers shared across routers.

`output_dirs.utils.validate_root` and `validate_under_root` are imported by
every domain that accepts a user-supplied path (downloads, targets, library,
app_config), so the error-branch behaviour they raise is part of the public
HTTP contract — exercise each one directly rather than only via the routers.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.output_dirs.utils import (
    coerce_optional,
    validate_root,
    validate_under_root,
)


class TestCoerceOptional:
    def test_returns_none_for_none(self) -> None:
        assert coerce_optional(None) is None

    def test_strips_surrounding_whitespace(self) -> None:
        assert coerce_optional("  /mnt/media  ") == "/mnt/media"

    def test_blank_string_becomes_none(self) -> None:
        # Empty after stripping → semantically "unset", which the routers treat
        # as a clear/reset of the field.
        assert coerce_optional("   ") is None
        assert coerce_optional("") is None


class TestValidateRoot:
    def test_creates_root_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "new-root"
        assert not target.exists()
        resolved = validate_root(str(target))
        assert resolved == target.resolve()
        assert target.is_dir()

    def test_accepts_existing_dir(self, tmp_path: Path) -> None:
        existing = tmp_path / "media"
        existing.mkdir()
        resolved = validate_root(str(existing))
        assert resolved == existing.resolve()

    def test_rejects_relative_path(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            validate_root("relative/path")
        assert exc_info.value.status_code == 400
        assert "absolute" in exc_info.value.detail

    def test_rejects_when_parent_missing(self, tmp_path: Path) -> None:
        missing_parent = tmp_path / "no-such-dir" / "media"
        with pytest.raises(HTTPException) as exc_info:
            validate_root(str(missing_parent))
        assert exc_info.value.status_code == 400
        assert "parent" in exc_info.value.detail

    def test_rejects_when_mkdir_fails(self, tmp_path: Path) -> None:
        # Path component that exists as a regular file blocks mkdir.
        collider = tmp_path / "file"
        collider.write_bytes(b"")
        with pytest.raises(HTTPException) as exc_info:
            validate_root(str(collider / "would-be-root"))
        assert exc_info.value.status_code == 400
        assert "cannot create root" in exc_info.value.detail

    def test_rejects_when_not_writable(self, tmp_path: Path, monkeypatch) -> None:
        # Force the probe write to raise PermissionError so we cover the
        # non-writable branch without depending on real chmod (which may not
        # apply under root in CI containers).
        from backend.output_dirs import utils as utils_mod

        root = tmp_path / "ro-root"
        root.mkdir()

        original = Path.write_bytes

        def deny_writes(self: Path, *args: object, **kwargs: object) -> int:
            if self.name == utils_mod._PROBE_NAME:
                raise PermissionError("readonly")
            return original(self, *args, **kwargs)  # type: ignore[return-value]

        monkeypatch.setattr(Path, "write_bytes", deny_writes)
        with pytest.raises(HTTPException) as exc_info:
            validate_root(str(root))
        assert exc_info.value.status_code == 400
        assert "not writable" in exc_info.value.detail


class TestValidateUnderRoot:
    def test_accepts_path_under_root(self, tmp_path: Path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        out = root / "Manga"
        resolved = validate_under_root(str(out), root)
        assert resolved == out.resolve()
        assert out.is_dir()

    def test_accepts_root_itself(self, tmp_path: Path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        # The router uses this when postprocess_default_output_dir == root.
        resolved = validate_under_root(str(root), root)
        assert resolved == root.resolve()

    def test_rejects_relative_path(self, tmp_path: Path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        with pytest.raises(HTTPException) as exc_info:
            validate_under_root("relative", root)
        assert exc_info.value.status_code == 400
        assert "absolute" in exc_info.value.detail
        assert "output_dir" in exc_info.value.detail

    def test_uses_custom_field_in_error_message(self, tmp_path: Path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        with pytest.raises(HTTPException) as exc_info:
            validate_under_root("relative", root, field="default")
        assert "default must be an absolute path" in exc_info.value.detail

    def test_rejects_path_outside_root(self, tmp_path: Path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        with pytest.raises(HTTPException) as exc_info:
            validate_under_root(str(outside), root)
        assert exc_info.value.status_code == 400
        assert "must be under root" in exc_info.value.detail
        assert str(root.resolve()) in exc_info.value.detail

    def test_rejects_when_mkdir_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        collider = root / "file"
        collider.write_bytes(b"")
        with pytest.raises(HTTPException) as exc_info:
            validate_under_root(str(collider / "would-be-dir"), root)
        assert exc_info.value.status_code == 400
        assert "cannot create output_dir" in exc_info.value.detail

    def test_skips_create_when_disabled(self, tmp_path: Path) -> None:
        # `create=False` is used when callers only want to *check* a path
        # without materialising it — e.g. when validating a previously stored
        # value that should not be implicitly recreated if it was removed.
        root = tmp_path / "media"
        root.mkdir()
        missing = root / "ghost"
        # Should not raise even though `missing` doesn't exist on disk.
        result = validate_under_root(str(missing), root, create=False)
        assert result == missing.resolve()
        assert not missing.exists()

    def test_rejects_when_not_writable(self, tmp_path: Path, monkeypatch) -> None:
        from backend.output_dirs import utils as utils_mod

        root = tmp_path / "media"
        root.mkdir()
        out = root / "ro-out"

        original = Path.write_bytes

        def deny_writes(self: Path, *args: object, **kwargs: object) -> int:
            if self.name == utils_mod._PROBE_NAME:
                raise PermissionError("readonly")
            return original(self, *args, **kwargs)  # type: ignore[return-value]

        monkeypatch.setattr(Path, "write_bytes", deny_writes)
        with pytest.raises(HTTPException) as exc_info:
            validate_under_root(str(out), root)
        assert exc_info.value.status_code == 400
        assert "output_dir is not writable" in exc_info.value.detail
