"""独立 FastAPI 路由、内存 SQLite；不导入 app.main，不连接真实 Agent。"""
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from app.models import Base, User, Script, Run, Issue
from app.diagnostic_models import IssueDiagnostic
from app.database import get_db
from app.auth import get_current_user
from app.routers import issues, settings
from app.services.diagnostic_policy import DiagnosticPolicy
from app.services.issue_diagnostics import cleanup_issue_diagnostics, bounded_log, MAX_LOG_BYTES
from client.runtime import diagnostics as collector


@pytest.fixture
def isolated(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    users = [User(id=i, username=f'u{i}', display_name=f'u{i}', password_hash='fake', role=role) for i, role in [(1, 'operator'), (2, 'operator'), (3, 'admin'), (4, 'developer')]]
    db.add_all(users)
    db.add(Script(id=1, name='test'))
    db.add(Run(id=1, user_id=1, script_id=1, script_version=7, params=json.dumps({'password': 'synthetic-secret', 'ordinary': 'normal'}), error_msg='synthetic-secret failed'))
    db.commit()
    app = FastAPI()
    app.include_router(issues.router)
    app.include_router(settings.router)
    identity = {'user': users[0]}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity['user']
    monkeypatch.setattr(issues, 'write_audit', lambda *a, **k: None)
    monkeypatch.setattr(settings, 'write_audit', lambda *a, **k: None)
    monkeypatch.setattr(issues, 'accessible_script_ids', lambda user: [])
    monkeypatch.setattr(issues, 'accessible_user_ids', lambda user: [])
    monkeypatch.setattr(issues, 'capture_run_log', lambda *a, **k: 'bounded execution log')
    with TestClient(app) as client:
        yield client, db, identity, users
    db.close()
    engine.dispose()


def request(**kwargs):
    return {'title': 'test', **kwargs}


@pytest.mark.parametrize('extra', [
    {'diagnostics': {}}, {'include_run_log': True, 'run_id': 1},
    {'include_run_summary': True, 'run_id': 1},
])
def test_consent_rechecked_for_preview_and_create(isolated, extra):
    client, db, _, _ = isolated
    for endpoint in ['/api/issues/preview', '/api/issues']:
        assert client.post(endpoint, json=request(**extra)).status_code == 422
    assert db.query(Issue).count() == 0


@pytest.mark.parametrize('section', ['logs', 'params', 'summary'])
def test_section_redaction_switch_and_sensitive_field_removal(section):
    policy = DiagnosticPolicy(**{'redact_' + section: False})
    assert policy.weakens(DiagnosticPolicy())
    if section == 'params':
        assert policy.params({'password': 'synthetic'})['password'] == 'synthetic'
    else:
        assert policy.text('password=synthetic', section) == 'password=synthetic'
    previous = DiagnosticPolicy(enabled=False, custom_sensitive_fields=['business'])
    assert DiagnosticPolicy(enabled=False).weakens(previous)
    assert not DiagnosticPolicy(enabled=False, custom_sensitive_fields=['BUSINESS']).weakens(previous)


def test_bounded_log_counts_marker_in_line_budget():
    text = bounded_log('line\n' * 2000, policy=DiagnosticPolicy(enabled=False))
    assert len(text.splitlines()) <= 500
    assert len(text.encode('utf-8')) <= MAX_LOG_BYTES


def test_frozen_migration_schema_roundtrip():
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    path = Path(__file__).resolve().parents[2] / 'backend/alembic/versions/0008_issue_diagnostics.py'
    spec = importlib.util.spec_from_file_location('diagnostic_migration_test', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE issues (id INTEGER PRIMARY KEY)')
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()
            assert {column['name'] for column in inspect(connection).get_columns('issue_diagnostics')} == {'issue_id', 'state', 'payload_json', 'created_at', 'expires_at'}
            assert inspect(connection).get_indexes('issue_diagnostics')[0]['column_names'] == ['expires_at']
            migration.downgrade()
            assert 'issue_diagnostics' not in inspect(connection).get_table_names()
    finally:
        engine.dispose()


def test_body_limit_before_json_decoding(isolated):
    client, _, _, _ = isolated
    response = client.post('/api/issues/preview', content=b'{' + b'x' * (192 * 1024), headers={'Content-Type': 'application/json'})
    assert response.status_code == 413


def test_selected_logs_use_run_secrets_without_storing_params(isolated):
    client, _, _, _ = isolated
    item = client.post('/api/issues', json=request(run_id=1, diagnostics_consent=True, diagnostics={'application_logs': {'agent': 'synthetic-secret here'}})).json()
    assert item['run_params'] == '{}'
    response = client.get(f"/api/issues/{item['id']}/diagnostics")
    assert response.status_code == 200 and 'synthetic-secret' not in response.text


def test_web_only_and_no_implicit_run_summary(isolated):
    client, db, _, _ = isolated
    web = client.post('/api/issues', json=request()).json()
    assert web['run_id'] is None and web['diagnostic_state'] == 'not_collected'
    run = client.post('/api/issues', json=request(run_id=1)).json()
    assert run['script_version'] == 7
    assert run['run_params'] == '{}' and run['error_msg'] is None
    assert db.query(IssueDiagnostic).count() == 2


def test_preview_cancel_has_no_persistence_and_unknown_fields_rejected(isolated):
    client, db, _, _ = isolated
    response = client.post('/api/issues/preview', json=request(run_id=1, include_run_summary=True, diagnostics_consent=True))
    assert response.status_code == 200
    assert 'synthetic-secret' not in response.text
    assert '服务器' in response.json()['notice']
    assert db.query(Issue).count() == db.query(IssueDiagnostic).count() == 0
    assert client.post('/api/issues', json=request(diagnostics={'env': {}}, diagnostics_consent=True)).status_code == 422
    assert client.post('/api/issues', json=request(diagnostics={'application_logs': {'config': 'x'}}, diagnostics_consent=True)).status_code == 422
    assert client.post('/api/issues', json=request(diagnostics={}, diagnostics_consent='true')).status_code == 422


def test_permissions_rechecked_after_preview_and_controlled_download(isolated):
    client, db, identity, users = isolated
    payload = request(run_id=1, include_run_summary=True, diagnostics_consent=True)
    assert client.post('/api/issues/preview', json=payload).status_code == 200
    identity['user'] = users[1]
    assert client.post('/api/issues', json=payload).status_code == 403
    identity['user'] = users[0]
    issue = client.post('/api/issues', json=payload).json()
    for user in [users[1], users[3]]:
        identity['user'] = user
        assert client.get(f"/api/issues/{issue['id']}/diagnostics").status_code == 404
        assert client.get('/api/issues').json() == []
    identity['user'] = users[2]
    download = client.get(f"/api/issues/{issue['id']}/diagnostics")
    assert download.status_code == 200
    assert download.headers['cache-control'] == 'no-store'
    assert 'attachment' in download.headers['content-disposition']


def test_fixed_snapshot_expiry_no_run_fallback_and_cleanup(isolated):
    client, db, _, _ = isolated
    item = client.post('/api/issues', json=request(run_id=1, include_run_summary=True, include_run_log=True, diagnostics_consent=True)).json()
    run = db.get(Run, 1)
    run.script_version = 99
    run.error_msg = 'NEW RAW SECRET'
    run.params = '{"password":"NEW RAW SECRET"}'
    db.commit()
    data = client.get('/api/issues').json()[0]
    assert data['script_version'] == 7 and 'NEW RAW SECRET' not in str(data)
    row = db.get(IssueDiagnostic, item['id'])
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    data = client.get('/api/issues').json()[0]
    assert data['diagnostic_state'] == 'expired' and data['run_params'] == '{}'
    assert client.get(f"/api/issues/{item['id']}/log").json()['log'] == ''
    assert client.get(f"/api/issues/{item['id']}/diagnostics").status_code == 410
    assert cleanup_issue_diagnostics(db) == 1
    db.commit()
    assert row.payload_json == '{}' and db.get(Issue, item['id']).log_snapshot == ''
    assert cleanup_issue_diagnostics(db) == 0


def test_cleanup_is_bounded_and_resumes_in_order(isolated):
    _, db, _, _ = isolated
    now = datetime.now(timezone.utc)
    expiry = now - timedelta(days=1)
    for i in range(1, 1002):
        db.add(Issue(id=i, user_id=1, title='batch', log_snapshot='selected log'))
        db.add(IssueDiagnostic(issue_id=i, state='collected', payload_json='{"metadata":{}}',
                               created_at=expiry - timedelta(days=1),
                               expires_at=now + timedelta(days=1) if i == 1001 else expiry))
    db.commit()
    assert cleanup_issue_diagnostics(db, now) == 500
    db.commit()
    assert db.query(IssueDiagnostic).filter(IssueDiagnostic.state == 'expired').count() == 500
    assert db.get(IssueDiagnostic, 500).state == 'expired'
    assert db.get(IssueDiagnostic, 501).state == 'collected'
    assert db.get(Issue, 500).log_snapshot == ''
    assert db.get(Issue, 501).log_snapshot == 'selected log'
    assert cleanup_issue_diagnostics(db, now) == 500
    db.commit()
    assert db.get(IssueDiagnostic, 1000).payload_json == '{}'
    assert db.get(Issue, 1000).log_snapshot == ''
    assert db.get(IssueDiagnostic, 1001).state == 'collected'
    assert cleanup_issue_diagnostics(db, now) == 0


def test_admin_policy_risk_retention_and_redaction_off(isolated):
    client, db, identity, users = isolated
    defaults = DiagnosticPolicy().model_dump()
    assert client.get('/api/settings/diagnostics').status_code == 403
    assert client.put('/api/settings/diagnostics', json=defaults).status_code == 403
    assert client.get('/api/settings/diagnostics/effective').status_code == 200
    identity['user'] = users[2]
    policy = {**defaults, 'custom_sensitive_fields': ['business'], 'retention_days': 1}
    assert client.put('/api/settings/diagnostics', json=policy).status_code == 200
    assert client.put('/api/settings/diagnostics', json={**policy, 'custom_sensitive_fields': []}).status_code == 409
    disabled = {**policy, 'enabled': False}
    assert client.put('/api/settings/diagnostics', json=disabled).status_code == 409
    assert client.put('/api/settings/diagnostics', json={**disabled, 'acknowledge_risk': True}).status_code == 200
    item = client.post('/api/issues', json=request(run_id=1, include_run_summary=True, diagnostics_consent=True)).json()
    assert 'synthetic-secret' in item['run_params']
    row = db.get(IssueDiagnostic, item['id'])
    assert row.expires_at - row.created_at == timedelta(days=1)
    assert client.post('/api/issues', json=request(diagnostics={'application_logs': {'agent': '中' * (192 * 1024)}}, diagnostics_consent=True)).status_code == 413
    assert len(bounded_log('中' * 100000, policy=DiagnosticPolicy(enabled=False)).encode()) <= MAX_LOG_BYTES
    assert client.put('/api/settings/diagnostics', json={**defaults, 'retention_days': 0}).status_code == 422


@pytest.fixture
def fake_paths(tmp_path):
    # Never call ClientPaths.from_environment or import/start an Agent.
    collector.update_effective_policy({})
    yield SimpleNamespace(logs_dir=tmp_path)
    collector.update_effective_policy({})


def test_collector_whitelist_bytebounds_policy_and_offline(fake_paths):
    path = fake_paths.logs_dir
    (path / 'agent.log').write_text(('token=synthetic-token\n' + '中' * 100 + '\n') * 700, encoding='utf-8')
    (path / 'desktop.log').write_text('business=synthetic-business\npassword=synthetic-password\n', encoding='utf-8')
    (path / 'config.json').write_text('do-not-collect', encoding='utf-8')
    policy = DiagnosticPolicy(custom_sensitive_fields=['business']).model_dump()
    collector.update_effective_policy(policy)
    data = collector.collect_diagnostics(fake_paths, 'fake-agent', True)
    assert data['collection_state'] == 'collected'
    assert set(data['application_logs']) == {'agent', 'desktop'}
    assert 'synthetic-' not in json.dumps(data)
    assert 'do-not-collect' not in json.dumps(data)
    assert all(len(v.encode()) <= collector.MAX_LOG_BYTES and len(v.splitlines()) <= collector.MAX_LOG_LINES for v in data['application_logs'].values())
    collector.update_effective_policy({**policy, 'enabled': False})
    assert 'synthetic-password' in collector.collect_diagnostics(fake_paths, 'fake', True)['application_logs']['desktop']
    assert 'synthetic-password' not in collector.collect_diagnostics(fake_paths, 'fake', False)['application_logs']['desktop']
    collector.update_effective_policy({'enabled': False})
    assert 'synthetic-password' not in collector.collect_diagnostics(fake_paths, 'fake', True)['application_logs']['desktop']


def test_collector_missing_files_and_symlinks(fake_paths):
    assert collector.collect_diagnostics(fake_paths, 'fake', False)['collection_state'] == 'partial'
    target = fake_paths.logs_dir / 'private.txt'
    target.write_text('private value', encoding='utf-8')
    try:
        (fake_paths.logs_dir / 'agent.log').symlink_to(target)
    except OSError:
        pytest.skip('Windows account cannot create symlinks')
    assert 'agent' not in collector.collect_diagnostics(fake_paths, 'fake', True)['application_logs']
    with pytest.raises(ValueError):
        collector.configure_application_logging('agent', fake_paths)


def test_application_logging_rotation_baseline_redaction_and_bounds(fake_paths):
    import logging
    root = logging.getLogger()
    previous_level = root.level
    handler = collector.configure_application_logging('desktop', fake_paths)
    try:
        assert collector.configure_application_logging('desktop', fake_paths) is handler
        assert handler.maxBytes == 256 * 1024 and handler.backupCount == 2
        collector.update_effective_policy(DiagnosticPolicy(enabled=False).model_dump())
        for i in range(35):
            record = logging.LogRecord('isolated', logging.INFO, '', 0, 'password=synthetic-password\nC:\\Users\\private\\file\n' + '中' * 20000, (), None)
            handler.handle(record)
        handler.flush()
        files = list(fake_paths.logs_dir.glob('desktop.log*'))
        assert len(files) == 3
        assert all(f.stat().st_size <= 256 * 1024 for f in files)
        assert all('synthetic-password' not in f.read_text(encoding='utf-8') and 'Users' not in f.read_text(encoding='utf-8') for f in files)
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(previous_level)
