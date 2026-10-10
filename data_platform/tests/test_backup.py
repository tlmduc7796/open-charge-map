from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_platform import backup


def _write_archive(path: Path, *, created_at: datetime) -> Path:
    path.write_bytes(b"custom postgres archive")
    record = {
        "backup_file": path.name,
        "database": "smart_ev_data",
        "created_at": created_at.isoformat(),
        "format": "postgresql-custom",
        "schema_revision": backup.EXPECTED_REVISION,
        "size_bytes": path.stat().st_size,
        "sha256": backup._sha256(path),
        "archive_list_check": "PASS",
    }
    backup._manifest_path(path).write_text(json.dumps(record), encoding="utf-8")
    return path


def test_backup_filename_rejects_path_injection() -> None:
    with pytest.raises(ValueError, match="database name"):
        backup._validate_database_name("smart_ev;drop database")


def test_verify_backup_checks_checksum_before_invoking_pg_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_archive(
        tmp_path / "smart-ev-smart_ev_data-20261009T120000Z.dump",
        created_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
    )
    archive.write_bytes(b"x" * archive.stat().st_size)
    monkeypatch.setattr(
        backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("pg_restore must not run for a bad checksum"),
    )

    with pytest.raises(ValueError, match="checksum"):
        backup.verify_backup(archive, env_file=tmp_path / "env", compose_file=tmp_path / "compose")


def test_prune_only_removes_expired_managed_backups_and_keeps_latest(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    archives = [
        _write_archive(
            tmp_path / f"smart-ev-smart_ev_data-2026090{day}T000000Z.dump",
            created_at=now - timedelta(days=day),
        )
        for day in (8, 7, 6)
    ]
    unrelated = tmp_path / "keep-this.dump"
    unrelated.write_bytes(b"not managed")

    removed = backup.prune_backups(
        tmp_path,
        older_than_days=5,
        keep_last=1,
        now=now,
    )

    assert set(removed) == set(archives[:2])
    assert not archives[0].exists()
    assert not backup._manifest_path(archives[0]).exists()
    assert not archives[1].exists()
    assert not backup._manifest_path(archives[1]).exists()
    assert archives[2].is_file()
    assert unrelated.read_bytes() == b"not managed"


def test_create_backup_streams_pg_dump_and_writes_verified_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env.release"
    env_file.write_text("POSTGRES_PASSWORD=abc123\n", encoding="utf-8")
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return datetime(2026, 10, 9, 12, 30, 45, tzinfo=tz or UTC)

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        if "pg_dump" in command:
            kwargs["stdout"].write(b"valid custom archive bytes")
            return subprocess.CompletedProcess(command, 0, stderr=b"")
        if "pg_restore" in command:
            assert kwargs["stdin"].read() == b"valid custom archive bytes"
            return subprocess.CompletedProcess(command, 0, stdout=b"archive listing", stderr=b"")
        if "psql" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"{backup.EXPECTED_REVISION}\n",
                stderr="",
            )
        pytest.fail(f"unexpected command: {command}")

    monkeypatch.setattr(backup, "datetime", FrozenDateTime)
    monkeypatch.setattr(backup.subprocess, "run", fake_run)

    archive = backup.create_backup(
        output_dir=tmp_path / "backups",
        env_file=env_file,
        compose_file=compose_file,
    )

    assert archive.name == "smart-ev-smart_ev_data-20261009T123045Z.dump"
    assert archive.read_bytes() == b"valid custom archive bytes"
    manifest = json.loads(backup._manifest_path(archive).read_text(encoding="utf-8"))
    assert manifest["schema_revision"] == backup.EXPECTED_REVISION
    assert manifest["sha256"] == backup._sha256(archive)
    assert manifest["archive_list_check"] == "PASS"


def test_create_backup_can_stream_encrypt_and_manifest_with_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env.release"
    env_file.write_text("POSTGRES_PASSWORD=abc123\n", encoding="utf-8")
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    identity_file = tmp_path / "backup.agekey"
    identity_file.write_text("AGE-SECRET-KEY-TEST", encoding="utf-8")
    captured = {}

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return datetime(2026, 10, 9, 12, 30, 45, tzinfo=tz or UTC)

    monkeypatch.setattr(backup, "datetime", FrozenDateTime)
    monkeypatch.setattr(backup.shutil, "which", lambda _: "age")

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        if "psql" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"{backup.EXPECTED_REVISION}\n",
                stderr="",
            )
        pytest.fail(f"unexpected command: {command}")

    def fake_encrypt(_command, output_path, recipient):  # type: ignore[no-untyped-def]
        captured["recipient"] = recipient
        output_path.write_bytes(b"age-encrypted archive")

    def fake_restore_list(archive, **kwargs):  # type: ignore[no-untyped-def]
        captured["archive"] = archive
        captured.update(kwargs)

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    monkeypatch.setattr(backup, "_stream_encrypted_dump", fake_encrypt)
    monkeypatch.setattr(backup, "_run_pg_restore_list", fake_restore_list)

    archive = backup.create_backup(
        output_dir=tmp_path / "backups",
        env_file=env_file,
        compose_file=compose_file,
        age_recipient="age1publicrecipient",
        age_identity_file=identity_file,
    )

    assert archive.name.endswith(".dump.age")
    assert archive.read_bytes() == b"age-encrypted archive"
    assert captured["recipient"] == "age1publicrecipient"
    assert captured["encryption"] == "age"
    assert captured["age_identity_file"] == identity_file
    manifest = json.loads(backup._manifest_path(archive).read_text(encoding="utf-8"))
    assert manifest["encryption"] == "age"
    assert manifest["sha256"] == backup._sha256(archive)


def test_verify_encrypted_archive_requires_identity_before_decryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_archive(
        tmp_path / "smart-ev-smart_ev_data-20261009T120000Z.dump.age",
        created_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
    )
    record = json.loads(backup._manifest_path(archive).read_text(encoding="utf-8"))
    record["encryption"] = "age"
    backup._manifest_path(archive).write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(backup.shutil, "which", lambda _: "age")

    with pytest.raises(ValueError, match="identity file is required"):
        backup.verify_backup(
            archive,
            env_file=tmp_path / "env",
            compose_file=tmp_path / "compose",
        )


def test_age_encrypted_dump_stream_round_trip(tmp_path: Path) -> None:
    if shutil.which("age") is None or shutil.which("age-keygen") is None:
        pytest.skip("age and age-keygen are required for this integration check")

    identity_file = tmp_path / "backup.agekey"
    subprocess.run(
        ["age-keygen", "-o", str(identity_file)],
        check=True,
        capture_output=True,
        text=True,
    )
    public_key_line = next(
        line for line in identity_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("# public key:")
    )
    recipient = public_key_line.split(":", 1)[1].strip()
    payload = b"custom PostgreSQL archive fixture\x00with binary data"
    encrypted_archive = tmp_path / "backup.dump.age.part"
    dump_command = [
        sys.executable,
        "-c",
        f"import sys; sys.stdout.buffer.write(bytes.fromhex('{payload.hex()}'))",
    ]

    backup._stream_encrypted_dump(dump_command, encrypted_archive, recipient)

    assert encrypted_archive.is_file()
    assert payload not in encrypted_archive.read_bytes()
    decrypted = subprocess.run(
        ["age", "--decrypt", "--identity", str(identity_file), str(encrypted_archive)],
        check=True,
        capture_output=True,
    )
    assert decrypted.stdout == payload


def test_archive_listing_drains_age_after_consumer_exits_early(tmp_path: Path) -> None:
    if shutil.which("age") is None or shutil.which("age-keygen") is None:
        pytest.skip("age and age-keygen are required for this integration check")

    identity_file = tmp_path / "backup.agekey"
    subprocess.run(
        ["age-keygen", "-o", str(identity_file)],
        check=True,
        capture_output=True,
        text=True,
    )
    recipient = next(
        line.split(":", 1)[1].strip()
        for line in identity_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("# public key:")
    )
    archive = tmp_path / "backup.dump.age"
    dump_command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'x' * 1048576)",
    ]
    backup._stream_encrypted_dump(dump_command, archive, recipient)
    early_consumer = [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1)"]

    decrypt = subprocess.Popen(
        ["age", "--decrypt", "--identity", str(identity_file), str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result = backup._run_command_from_age_stream(decrypt, early_consumer)
    assert result.returncode == 0
    assert decrypt.returncode == 0

    damaged_archive = tmp_path / "damaged.dump.age"
    damaged_bytes = bytearray(archive.read_bytes())
    damaged_bytes[-1] ^= 1
    damaged_archive.write_bytes(damaged_bytes)
    damaged_decrypt = subprocess.Popen(
        [
            "age",
            "--decrypt",
            "--identity",
            str(identity_file),
            str(damaged_archive),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    with pytest.raises(RuntimeError, match="decrypt"):
        backup._run_command_from_age_stream(damaged_decrypt, early_consumer)
    assert damaged_decrypt.returncode != 0


def test_restore_refuses_to_target_source_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_archive(
        tmp_path / "smart-ev-smart_ev_data-20261009T120000Z.dump",
        created_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
    )
    monkeypatch.setattr(backup, "_run_pg_restore_list", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="new database"):
        backup.restore_to_new_database(
            archive,
            "smart_ev_data",
            env_file=tmp_path / "env",
            compose_file=tmp_path / "compose",
        )


def test_restore_validates_and_restores_to_new_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_archive(
        tmp_path / "smart-ev-smart_ev_data-20261009T120000Z.dump",
        created_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
    )
    env_file = tmp_path / ".env.release"
    env_file.write_text("POSTGRES_PASSWORD=abc123\n", encoding="utf-8")
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    commands: list[list[str]] = []
    monkeypatch.setattr(backup, "_run_pg_restore_list", lambda *_args, **_kwargs: None)

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        commands.append(command)
        if "psql" in command:
            sql = command[command.index("-c") + 1]
            if "pg_database" in sql:
                output = ""
            elif "alembic_version" in sql:
                output = backup.EXPECTED_REVISION
            else:
                output = "16"
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
        if "createdb" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "pg_restore" in command:
            assert "--single-transaction" in command
            assert kwargs["stdin"].read() == archive.read_bytes()
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        pytest.fail(f"unexpected command: {command}")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)

    revision = backup.restore_to_new_database(
        archive,
        "smart_ev_restore_check",
        env_file=env_file,
        compose_file=compose_file,
    )

    assert revision == backup.EXPECTED_REVISION
    assert any("createdb" in command for command in commands)
    assert any(
        "pg_restore" in command and "--single-transaction" in command
        for command in commands
    )


def test_restore_refuses_existing_target_without_running_createdb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_archive(
        tmp_path / "smart-ev-smart_ev_data-20261009T120000Z.dump",
        created_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
    )
    env_file = tmp_path / ".env.release"
    env_file.write_text("POSTGRES_PASSWORD=abc123\n", encoding="utf-8")
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(backup, "_run_pg_restore_list", lambda *_args, **_kwargs: None)

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        assert "psql" in command
        return subprocess.CompletedProcess(command, 0, stdout="1", stderr="")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)

    with pytest.raises(FileExistsError, match="already exists"):
        backup.restore_to_new_database(
            archive,
            "smart_ev_restore_check",
            env_file=env_file,
            compose_file=compose_file,
        )
