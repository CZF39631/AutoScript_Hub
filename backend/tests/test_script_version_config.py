import json
import pytest
from app.models import Script, ScriptVersion


def make_script(session, config):
    with session() as db:
        script = Script(name='version-fixture', latest_version=2, config_json='{"params": [{"key": "latest"}]}')
        db.add(script)
        db.flush()
        db.add(ScriptVersion(script_id=script.id, version=1, file_path='fixture-only', config_json=config))
        script_id = script.id
        db.commit()
        return script_id


def test_config_uses_requested_version_not_latest(client, fresh_db, admin_token):
    old = {'params': [{'key': 'old', 'type': 'string'}]}
    script_id = make_script(fresh_db[0], json.dumps(old))
    r = client.get(f'/api/scripts/{script_id}/versions/1/config', headers={'Authorization': f'Bearer {admin_token}'})
    assert r.status_code == 200
    assert r.json() == {'version': 1, 'config': old}
    assert client.get(f'/api/scripts/{script_id}/versions/99/config', headers={'Authorization': f'Bearer {admin_token}'}).status_code == 404


@pytest.mark.parametrize('config', [None, 'null', '[]', '{broken'])
def test_invalid_version_config_fails_closed(client, fresh_db, admin_token, config):
    script_id = make_script(fresh_db[0], config)
    r = client.get(f'/api/scripts/{script_id}/versions/1/config', headers={'Authorization': f'Bearer {admin_token}'})
    assert r.status_code == 409


def test_version_config_respects_group_boundary_and_auth(client, fresh_db, op_token):
    script_id = make_script(fresh_db[0], '{}')
    url = f'/api/scripts/{script_id}/versions/1/config'
    assert client.get(url).status_code in (401, 403)
    assert client.get(url, headers={'Authorization': f'Bearer {op_token}'}).status_code == 404
