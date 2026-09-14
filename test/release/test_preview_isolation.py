from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_preview_compose_cannot_reuse_production_service_or_bind_data():
    config = yaml.safe_load((ROOT / 'deploy/compose.preview.yaml').read_text(encoding='utf-8'))
    assert config['name'] == 'autoscript-hub-preview'
    assert set(config['services']) == {'preview_server'}
    service = config['services']['preview_server']
    assert service['volumes'] == ['preview_data:/data']
    assert set(config['volumes']) == {'preview_data'}
    assert 'AUTOSCRIPT_PREVIEW_PORT:?' in service['ports'][0]
    assert ':-127.0.0.1' in service['ports'][0]
    assert service['environment']['EXTERNAL_AUTH_ENABLED'] == 'false'
    assert 'AUTOSCRIPT_PREVIEW_JWT_SECRET:?' in service['environment']['JWT_SECRET']
    assert 'AUTOSCRIPT_PREVIEW_ADMIN_PASSWORD:?' in service['environment']['ADMIN_PASSWORD']
    assert 'env_file' not in service  # No accidental injection of a production env file.
    assert not service.get('privileged')


def test_production_compose_keeps_its_existing_service():
    config = yaml.safe_load((ROOT / 'deploy/compose.yaml').read_text(encoding='utf-8'))
    assert 'server' in config['services']
    assert 'preview_server' not in config['services']
