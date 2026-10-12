import shutil
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from company_os.cli import setup


def test_setup_creates_secret_template_and_migrated_database(tmp_path, monkeypatch, capsys):
    project = Path(__file__).parents[1]
    shutil.copy(project / "alembic.ini", tmp_path / "alembic.ini")
    shutil.copytree(project / "migrations", tmp_path / "migrations")
    monkeypatch.chdir(tmp_path)

    setup("sqlite:///runtime/company.db", "smoke", "operator")

    environment = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "KOZPHY_IDENTITIES_JSON=" in environment
    assert "POSTGRES_PASSWORD=" in environment
    assert "KOZPHY_ENVIRONMENT=local" in environment
    assert "Local operator token (shown once" in capsys.readouterr().out
    with sqlite3.connect(tmp_path / "runtime/company.db") as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0002",)


def test_upgrade_from_existing_v1_adds_authorization_table(tmp_path, monkeypatch):
    project = Path(__file__).parents[1]
    shutil.copy(project / "alembic.ini", tmp_path / "alembic.ini")
    shutil.copytree(project / "migrations", tmp_path / "migrations")
    (tmp_path / ".env").write_text(
        "KOZPHY_ENVIRONMENT=local\n"
        "KOZPHY_DATABASE_URL=sqlite:///runtime/legacy.db\n"
        "KOZPHY_IDENTITIES_JSON={}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    config = Config("alembic.ini")
    command.upgrade(config, "0001")
    with sqlite3.connect(tmp_path / "runtime/legacy.db") as connection:
        old_auth_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='authorizations'"
        ).fetchone()
    assert old_auth_table is None

    command.upgrade(config, "head")
    with sqlite3.connect(tmp_path / "runtime/legacy.db") as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        auth_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='authorizations'"
        ).fetchone()
    assert revision == ("0002",) and auth_table == ("authorizations",)
