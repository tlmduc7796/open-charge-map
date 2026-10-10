"""Safe PostgreSQL backup, archive verification, restore, and retention helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.release"
DEFAULT_COMPOSE_FILE = REPOSITORY_ROOT / "compose.release.yaml"
DEFAULT_BACKUP_DIR = Path.home() / ".smart-ev" / "backups" / "postgres"
EXPECTED_REVISION = "0020_path_safe_ids"
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
BACKUP_NAME_PATTERN = re.compile(
    r"^smart-ev-[A-Za-z][A-Za-z0-9_]{0,62}-\d{8}T\d{6}Z\.dump(?:\.age)?$"
)


def _compose_command(env_file: Path, compose_file: Path, *args: str) -> list[str]:
    if not env_file.is_file():
        raise FileNotFoundError(f"release environment file not found: {env_file}")
    if not compose_file.is_file():
        raise FileNotFoundError(f"release compose file not found: {compose_file}")
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file.resolve()),
        "-f",
        str(compose_file.resolve()),
        *args,
    ]


def _run_text(command: list[str], *, cwd: Path = REPOSITORY_ROOT) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(message)
    return result.stdout.strip()


def _psql_command(
    env_file: Path, compose_file: Path, database: str, sql: str
) -> list[str]:
    return _compose_command(
        env_file,
        compose_file,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "smart_ev",
        "-d",
        database,
        "-At",
        "-c",
        sql,
    )


def _database_url_from_env(env_file: Path) -> str:
    """Get the configured release URL without invoking a shell or printing secrets."""
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    password = values.get("POSTGRES_PASSWORD", "")
    if not password:
        raise ValueError("POSTGRES_PASSWORD must be set in the release env file")
    return f"postgresql+psycopg://smart_ev:{password}@127.0.0.1:5433/smart_ev_data"


def _validate_database_name(name: str) -> None:
    if not DATABASE_NAME_PATTERN.fullmatch(name):
        raise ValueError("database name may contain only letters, digits and underscores")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(archive: Path) -> Path:
    return archive.with_suffix(archive.suffix + ".json")


def _validate_age_identity(identity_file: Path | None) -> Path:
    if shutil.which("age") is None:
        raise FileNotFoundError("age is required for encrypted backup operations")
    if identity_file is None:
        raise ValueError("an age identity file is required for encrypted backup operations")
    identity = identity_file.expanduser().resolve()
    if not identity.is_file():
        raise FileNotFoundError("age identity file was not found")
    return identity


def _finish_age_process(process: subprocess.Popen) -> bytes:
    if process.stdout is not None:
        process.stdout.close()
        process.stdout = None
    return process.communicate()[1]


def _run_command_from_age_stream(
    age_process: subprocess.Popen, command: list[str]
) -> subprocess.CompletedProcess[bytes]:
    """Feed decrypted bytes to a consumer, draining age to authenticate EOF.

    ``pg_restore --list`` may exit after reading only the custom archive header.
    Continue consuming the age stream after the consumer closes stdin so age can
    verify the ciphertext authentication tag instead of failing with SIGPIPE.
    """
    assert age_process.stdout is not None
    with tempfile.TemporaryFile() as command_error:
        consumer = subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=command_error,
        )
        assert consumer.stdin is not None
        try:
            forward_to_consumer = True
            while chunk := age_process.stdout.read(64 * 1024):
                if not forward_to_consumer:
                    continue
                try:
                    consumer.stdin.write(chunk)
                    consumer.stdin.flush()
                except BrokenPipeError:
                    forward_to_consumer = False
                    try:
                        consumer.stdin.close()
                    except BrokenPipeError:
                        pass
            if not consumer.stdin.closed:
                try:
                    consumer.stdin.close()
                except BrokenPipeError:
                    pass
            consumer_status = consumer.wait()
            age_error = _finish_age_process(age_process)
            if age_process.returncode:
                raise RuntimeError(
                    age_error.decode("utf-8", errors="replace").strip()
                    or "age could not decrypt backup"
                )
            command_error.seek(0)
            return subprocess.CompletedProcess(
                command,
                consumer_status,
                stdout=b"",
                stderr=command_error.read(),
            )
        except Exception:
            if consumer.poll() is None:
                consumer.kill()
                consumer.wait()
            if not consumer.stdin.closed:
                consumer.stdin.close()
            raise


def _stream_encrypted_dump(command: list[str], output_path: Path, recipient: str) -> None:
    if shutil.which("age") is None:
        raise FileNotFoundError("age is required to create encrypted backups")
    if not recipient.strip():
        raise ValueError("age recipient must not be empty")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as dump_error, tempfile.TemporaryFile() as age_error:
        dump_process = subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=dump_error,
        )
        age_process = None
        try:
            assert dump_process.stdout is not None
            with output_path.open("xb") as encrypted_output:
                try:
                    os.chmod(output_path, 0o600)
                except OSError:
                    pass
                age_process = subprocess.Popen(
                    ["age", "--recipient", recipient],
                    stdin=dump_process.stdout,
                    stdout=encrypted_output,
                    stderr=age_error,
                )
                dump_process.stdout.close()
                age_status = age_process.wait()
                dump_status = dump_process.wait()
                encrypted_output.flush()
                os.fsync(encrypted_output.fileno())
        except Exception:
            if age_process is not None and age_process.poll() is None:
                age_process.kill()
                age_process.wait()
            if dump_process.poll() is None:
                dump_process.kill()
                dump_process.wait()
            output_path.unlink(missing_ok=True)
            raise
        if age_status or dump_status:
            age_error.seek(0)
            dump_error.seek(0)
            details = age_error.read() or dump_error.read()
            output_path.unlink(missing_ok=True)
            message = details.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or "age encryption or pg_dump failed")


def _run_pg_restore_list(
    archive: Path,
    *,
    env_file: Path,
    compose_file: Path,
    encryption: str = "none",
    age_identity_file: Path | None = None,
) -> None:
    identity = _validate_age_identity(age_identity_file) if encryption == "age" else None
    command = _compose_command(
        env_file,
        compose_file,
        "exec",
        "-T",
        "postgres",
        "pg_restore",
        "--list",
    )
    age_process = None
    try:
        if encryption == "age":
            assert identity is not None
            age_process = subprocess.Popen(
                ["age", "--decrypt", "--identity", str(identity), str(archive)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert age_process.stdout is not None
            result = _run_command_from_age_stream(age_process, command)
        else:
            with archive.open("rb") as stream:
                result = subprocess.run(
                    command, cwd=REPOSITORY_ROOT, stdin=stream, capture_output=True
                )
    finally:
        if age_process is not None and age_process.poll() is None:
            age_process.kill()
            age_process.wait()
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(error or f"pg_restore could not read {archive.name}")


def create_backup(
    *,
    output_dir: Path = DEFAULT_BACKUP_DIR,
    database: str = "smart_ev_data",
    env_file: Path = DEFAULT_ENV_FILE,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    age_recipient: str | None = None,
    age_identity_file: Path | None = None,
) -> Path:
    _validate_database_name(database)
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_file.resolve()
    compose_file = compose_file.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if age_recipient is not None and not age_recipient.strip():
        raise ValueError("age recipient must not be empty")
    encryption = "age" if age_recipient is not None else "none"
    if encryption == "age":
        _validate_age_identity(age_identity_file)
    extension = ".dump.age" if encryption == "age" else ".dump"
    archive_name = f"smart-ev-{database}-{timestamp}{extension}"
    archive = output_dir / archive_name
    partial = output_dir / f"{archive_name}.part"
    manifest = _manifest_path(archive)
    if archive.exists() or manifest.exists() or partial.exists():
        raise FileExistsError(f"backup already exists for timestamp {timestamp}")

    database_url = make_url(_database_url_from_env(env_file))
    if database_url.database != database:
        raise ValueError(
            f"release DATABASE_URL targets {database_url.database!r}, not requested {database!r}"
        )
    revision = _run_text(
        _psql_command(
            env_file,
            compose_file,
            database,
            "SELECT version_num FROM alembic_version",
        )
    )
    if revision != EXPECTED_REVISION:
        raise RuntimeError(
            f"refusing backup: schema revision is {revision!r}; expected {EXPECTED_REVISION}"
        )

    dump_command = _compose_command(
        env_file,
        compose_file,
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "-U",
        "smart_ev",
        "-d",
        database,
    )
    try:
        if encryption == "age":
            _stream_encrypted_dump(dump_command, partial, str(age_recipient))
        else:
            with partial.open("xb") as output:
                try:
                    os.chmod(partial, 0o600)
                except OSError:
                    pass
                result = subprocess.run(
                    dump_command,
                    cwd=REPOSITORY_ROOT,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                output.flush()
                os.fsync(output.fileno())
            if result.returncode:
                error = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(error or "pg_dump failed")
        if partial.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty archive")
        _run_pg_restore_list(
            partial,
            env_file=env_file,
            compose_file=compose_file,
            encryption=encryption,
            age_identity_file=age_identity_file,
        )
        checksum = _sha256(partial)
        partial.replace(archive)
        record = {
            "backup_file": archive_name,
            "database": database,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "format": "postgresql-custom",
            "encryption": encryption,
            "schema_revision": revision,
            "size_bytes": archive.stat().st_size,
            "sha256": checksum,
            "archive_list_check": "PASS",
        }
        temporary_manifest = manifest.with_suffix(manifest.suffix + ".part")
        temporary_manifest.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        try:
            os.chmod(temporary_manifest, 0o600)
        except OSError:
            pass
        temporary_manifest.replace(manifest)
        return archive
    except Exception:
        partial.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        manifest.with_suffix(manifest.suffix + ".part").unlink(missing_ok=True)
        raise


def verify_backup(
    archive: Path,
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    age_identity_file: Path | None = None,
) -> dict[str, Any]:
    archive = archive.resolve()
    if not archive.is_file() or not BACKUP_NAME_PATTERN.fullmatch(archive.name):
        raise ValueError("archive is missing or does not use the managed backup filename format")
    manifest_path = _manifest_path(archive)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"backup manifest not found: {manifest_path}")
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    if record.get("backup_file") != archive.name:
        raise ValueError("backup manifest does not match archive filename")
    if record.get("size_bytes") != archive.stat().st_size:
        raise ValueError("backup archive size does not match manifest")
    if record.get("sha256") != _sha256(archive):
        raise ValueError("backup archive checksum does not match manifest")
    encryption = record.get("encryption", "none")
    if encryption not in {"none", "age"}:
        raise ValueError("backup manifest declares an unsupported encryption format")
    _run_pg_restore_list(
        archive,
        env_file=env_file.resolve(),
        compose_file=compose_file.resolve(),
        encryption=encryption,
        age_identity_file=age_identity_file,
    )
    return record


def restore_to_new_database(
    archive: Path,
    target_database: str,
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    age_identity_file: Path | None = None,
) -> str:
    _validate_database_name(target_database)
    record = verify_backup(
        archive,
        env_file=env_file,
        compose_file=compose_file,
        age_identity_file=age_identity_file,
    )
    source_database = str(record.get("database", ""))
    _validate_database_name(source_database)
    if target_database == source_database:
        raise ValueError("restore target must be a new database name, never the source database")
    env_file = env_file.resolve()
    compose_file = compose_file.resolve()
    exists = _run_text(
        _psql_command(
            env_file,
            compose_file,
            "postgres",
            "SELECT 1 FROM pg_database WHERE datname = '" + target_database + "'",
        )
    )
    if exists:
        raise FileExistsError(f"restore target database already exists: {target_database}")
    _run_text(
        _compose_command(
            env_file,
            compose_file,
            "exec",
            "-T",
            "postgres",
            "createdb",
            "-U",
            "smart_ev",
            "--owner",
            "smart_ev",
            target_database,
        )
    )
    restore_command = _compose_command(
        env_file,
        compose_file,
        "exec",
        "-T",
        "postgres",
        "pg_restore",
        "--single-transaction",
        "--no-owner",
        "--no-acl",
        "-U",
        "smart_ev",
        "-d",
        target_database,
    )
    age_process = None
    try:
        if record.get("encryption", "none") == "age":
            identity = _validate_age_identity(age_identity_file)
            age_process = subprocess.Popen(
                ["age", "--decrypt", "--identity", str(identity), str(archive.resolve())],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert age_process.stdout is not None
            result = subprocess.run(
                restore_command,
                cwd=REPOSITORY_ROOT,
                stdin=age_process.stdout,
                capture_output=True,
                check=False,
            )
            age_error = _finish_age_process(age_process)
            if age_process.returncode:
                raise RuntimeError(
                    age_error.decode("utf-8", errors="replace").strip()
                    or "age could not decrypt backup"
                )
        else:
            with archive.resolve().open("rb") as stream:
                result = subprocess.run(
                    restore_command,
                    cwd=REPOSITORY_ROOT,
                    stdin=stream,
                    capture_output=True,
                    check=False,
                )
    finally:
        if age_process is not None and age_process.poll() is None:
            age_process.kill()
            age_process.wait()
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "restore failed; empty target database "
            f"{target_database!r} was retained for inspection: "
            + (error or "pg_restore failed")
        )
    restored_revision = _run_text(
        _psql_command(
            env_file,
            compose_file,
            target_database,
            "SELECT version_num FROM alembic_version",
        )
    )
    if restored_revision != record.get("schema_revision"):
        raise RuntimeError(
            f"restored schema revision {restored_revision!r} does not match backup manifest"
        )
    station_count = _run_text(
        _psql_command(
            env_file,
            compose_file,
            target_database,
            "SELECT count(*) FROM stations",
        )
    )
    if not station_count.isdigit() or int(station_count) < 1:
        raise RuntimeError("restore validation failed: station catalog is empty")
    return restored_revision


def prune_backups(
    output_dir: Path,
    *,
    older_than_days: int,
    keep_last: int = 2,
    now: datetime | None = None,
) -> list[Path]:
    if older_than_days <= 0 or keep_last < 0:
        raise ValueError("older_than_days must be positive and keep_last cannot be negative")
    output_dir = output_dir.resolve()
    if not output_dir.is_dir():
        return []
    cutoff = (now or datetime.now(UTC)) - timedelta(days=older_than_days)
    managed: list[tuple[datetime, Path, Path]] = []
    for manifest_path in output_dir.glob("smart-ev-*.dump*.json"):
        if manifest_path.resolve().parent != output_dir:
            continue
        try:
            record = json.loads(manifest_path.read_text(encoding="utf-8"))
            name = str(record.get("backup_file", ""))
            created_at = datetime.fromisoformat(str(record["created_at"]).replace("Z", "+00:00"))
            if created_at.tzinfo is None:
                continue
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        archive = output_dir / name
        if (
            not BACKUP_NAME_PATTERN.fullmatch(name)
            or archive.resolve().parent != output_dir
            or not archive.is_file()
            or manifest_path != _manifest_path(archive)
        ):
            continue
        managed.append((created_at, archive, manifest_path))
    managed.sort(key=lambda item: item[0], reverse=True)
    protected = {archive for _, archive, _ in managed[:keep_last]}
    removed: list[Path] = []
    for created_at, archive, manifest_path in managed:
        if created_at < cutoff and archive not in protected:
            archive.unlink()
            manifest_path.unlink()
            removed.append(archive)
    return removed
