import shutil
import sqlite3
from pathlib import Path

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
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0001",)
