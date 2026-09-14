from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.migrations import alembic_config, upgrade_database


def test_existing_settings_survive_policy_upgrade_and_downgrade(tmp_path):
    url = "sqlite:///" + str(tmp_path / "diagnostic-policy.db")
    config = alembic_config(url)
    upgrade_database(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE server_settings SET interval_hours=12 WHERE id=1"))
    engine.dispose()
    command.downgrade(config, "0005_server_settings")
    engine = create_engine(url)
    assert "diagnostic_policy_json" not in {c["name"] for c in inspect(engine).get_columns("server_settings")}
    engine.dispose()
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT interval_hours, diagnostic_policy_json FROM server_settings WHERE id=1")).one()
        assert tuple(row) == (12, "{}")
    engine.dispose()
