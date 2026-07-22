import os
import io
import zipfile

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _upload(client, token, filename="sample_script.py"):
    path = os.path.join(FIXTURE_DIR, filename)
    with open(path, "rb") as f:
        return client.post(
            "/api/scripts/upload",
            files={"file": (filename, f, "text/x-python")},
            data={"changelog": "test upload"},
            headers={"Authorization": f"Bearer {token}"},
        )


def test_upload_py_script(client, dev_token):
    resp = _upload(client, dev_token)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "测试脚本"
    assert data["latest_version"] == 1
    assert data["status"] == "active"


def test_upload_requires_dev_role(client, op_token):
    resp = _upload(client, op_token)
    assert resp.status_code == 403


def test_list_scripts(client, dev_token):
    _upload(client, dev_token)
    resp = client.get("/api/scripts", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_get_script_detail(client, dev_token):
    upload_resp = _upload(client, dev_token)
    sid = upload_resp.json()["id"]
    resp = client.get(f"/api/scripts/{sid}", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200
    assert resp.json()["config_json"] is not None


def test_disable_enable_script(client, dev_token):
    upload_resp = _upload(client, dev_token)
    sid = upload_resp.json()["id"]
    resp = client.post(f"/api/scripts/{sid}/disable", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200
    resp = client.post(f"/api/scripts/{sid}/enable", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200


def test_upload_new_version(client, dev_token):
    upload_resp = _upload(client, dev_token)
    sid = upload_resp.json()["id"]
    path = os.path.join(FIXTURE_DIR, "sample_script.py")
    with open(path, "rb") as f:
        resp = client.post(
            f"/api/scripts/{sid}/upload-version",
            files={"file": ("sample_script.py", f, "text/x-python")},
            data={"changelog": "v2 fix"},
            headers={"Authorization": f"Bearer {dev_token}"},
        )
    assert resp.status_code == 200
    assert resp.json()["latest_version"] == 2


def test_list_versions(client, dev_token):
    upload_resp = _upload(client, dev_token)
    sid = upload_resp.json()["id"]
    resp = client.get(f"/api/scripts/{sid}/versions", headers={"Authorization": f"Bearer {dev_token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_upload_rejects_main_signature_mismatch_with_structured_error(client, dev_token):
    source = b'''\
def config():
    return {"name":"bad","version":"1.0.0","description":"bad","category":"test","params":[{"key":"value","type":"text","label":"Value"}],"requirements":[],"timeout":60}

def main():
    return None
'''

    response = client.post(
        "/api/scripts/upload",
        files={"file": ("bad.py", source, "text/x-python")},
        headers={"Authorization": f"Bearer {dev_token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "main.signature"


def test_upload_rejects_zip_path_traversal(client, dev_token):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.py", "raise RuntimeError('unsafe')")
        bundle.writestr(
            "main.py",
            "def config(): return {'name':'x'}\ndef main(): return None\n",
        )

    response = client.post(
        "/api/scripts/upload",
        files={"file": ("unsafe.zip", archive.getvalue(), "application/zip")},
        headers={"Authorization": f"Bearer {dev_token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "zip.unsafe-path"
