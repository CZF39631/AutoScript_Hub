from datetime import datetime, timedelta, timezone

from app import scheduler
from app.models import Agent, Run, Script, User


def test_heartbeat_scan_handles_sqlite_naive_started_at(fresh_db, monkeypatch):
    TestSession, _ = fresh_db
    db = TestSession()
    user = User(
        username="watchdog-user",
        password_hash="unused",
        display_name="Watchdog User",
        role="operator",
        status="active",
    )
    script = Script(name="watchdog-script", type="py", latest_version=1, status="active")
    db.add_all([user, script])
    db.flush()
    agent = Agent(
        machine_name="offline-pc",
        user_id=user.id,
        status="online",
        last_heartbeat=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.add(agent)
    db.flush()
    run = Run(
        script_id=script.id,
        script_version=1,
        user_id=user.id,
        agent_id=agent.id,
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    db.add(run)
    db.commit()
    agent_id = agent.id
    run_id = run.id
    db.close()
    monkeypatch.setattr(scheduler, "SessionLocal", TestSession)
    scheduler._heartbeat_scan()

    db = TestSession()
    saved_agent = db.query(Agent).filter(Agent.id == agent_id).one()
    saved_run = db.query(Run).filter(Run.id == run_id).one()
    assert saved_agent.status == "offline"
    assert saved_run.status == "failed"
    assert saved_run.error_msg == "Agent heartbeat timeout (server-side watchdog)"
    assert 100 <= saved_run.duration_sec <= 180
    db.close()
