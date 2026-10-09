from pathlib import Path

import storage


def test_storage_media_dispatches_windows_result(monkeypatch) -> None:
    monkeypatch.setattr(
        storage,
        "_windows_media",
        lambda _path: (storage.StorageMediaKind.SOLID_STATE, "mocked"),
    )

    result = storage.storage_media_for_path(Path.cwd(), system="Windows")

    assert result.kind == storage.StorageMediaKind.SOLID_STATE
    assert result.is_ssd is True
    assert result.detail == "mocked"


def test_storage_media_unknown_platform_is_conservative() -> None:
    result = storage.storage_media_for_path(Path.cwd(), system="Plan9")

    assert result.kind == storage.StorageMediaKind.UNKNOWN
    assert result.is_ssd is None
    assert "unsupported" in result.detail


def test_windows_volume_device_accepts_drive_letter_and_rejects_unc() -> None:
    assert storage._windows_volume_device(r"E:\scratch") == r"\\.\E:"
    assert storage._windows_volume_device(r"\\server\share") is None


def test_linux_mount_source_uses_longest_matching_mount(tmp_path: Path) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 8:1 / / rw - ext4 /dev/sda1 rw\n"
        "2 1 8:2 / /mnt/fast rw - ext4 /dev/nvme0n1p1 rw\n",
        encoding="utf-8",
    )

    assert (
        storage._linux_mount_source(
            Path("/mnt/fast/library"),
            mountinfo,
            resolved_path="/mnt/fast/library",
        )
        == "/dev/nvme0n1p1"
    )


def test_linux_mount_source_matches_root_mount(tmp_path: Path) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("1 0 8:1 / / rw - ext4 /dev/sda1 rw\n", encoding="utf-8")

    assert (
        storage._linux_mount_source(
            Path("/var/lib/app"),
            mountinfo,
            resolved_path="/var/lib/app",
        )
        == "/dev/sda1"
    )


def test_linux_rotational_flag_reads_device_or_parent(tmp_path: Path) -> None:
    device = tmp_path / "nvme0n1p1"
    device.mkdir()
    queue = device / "queue"
    queue.mkdir()
    (queue / "rotational").write_text("0\n", encoding="ascii")
    assert (
        storage._linux_rotational_flag(
            "/dev/nvme0n1p1",
            tmp_path,
            resolved_source="/dev/nvme0n1p1",
        )
        is False
    )


def test_linux_non_block_mount_is_unknown(monkeypatch) -> None:
    monkeypatch.setattr(storage, "_linux_mount_source", lambda _path: "overlay")

    kind, detail = storage._linux_media(Path("/tmp"))

    assert kind == storage.StorageMediaKind.UNKNOWN
    assert "unavailable" in detail
