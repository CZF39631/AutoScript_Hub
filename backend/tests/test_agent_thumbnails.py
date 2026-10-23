import io

import pytest
from PIL import Image

from app.services import agent_thumbnails


def _headers(user_token, agent_token=None):
    headers = {"Authorization": "Bearer {}".format(user_token)}
    if agent_token is not None:
        headers["X-Agent-Token"] = agent_token
    return headers


def _register(client, token, uid, *, mode="managed"):
    response = client.post(
        "/api/agents/register",
        json={"device_uid": uid, "machine_name": uid, "mode": mode},
        headers=_headers(token),
    )
    assert response.status_code == 200
    return response.json()


def _image_bytes(image_format="JPEG", size=(32, 24), color=(30, 80, 120)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    return output.getvalue()


@pytest.fixture(autouse=True)
def isolated_thumbnail_dir(tmp_path, monkeypatch):
    directory = tmp_path / "thumbnails"
    monkeypatch.setattr(agent_thumbnails, "THUMBNAILS_DIR", str(directory))
    return directory


def test_managed_agent_thumbnail_round_trip_metadata_is_admin_only_and_not_in_regular_api(
    client, admin_token, dev_token, isolated_thumbnail_dir
):
    agent = _register(client, dev_token, "thumbnail-round-trip")
    first_jpeg = _image_bytes(color=(1, 2, 3))
    uploaded = client.post(
        "/api/agents/{}/thumbnail".format(agent["id"]),
        content=first_jpeg,
        headers={**_headers(dev_token, agent["agent_token"]), "Content-Type": "image/jpeg"},
    )

    assert uploaded.status_code == 200
    assert uploaded.json()["thumbnail_size"] == len(first_jpeg)
    assert uploaded.json()["thumbnail_updated_at"] is not None
    assert uploaded.json()["width"] == 32
    assert uploaded.json()["height"] == 24

    managed_list = client.get(
        "/api/admin/managed-agents", headers=_headers(admin_token)
    )
    assert managed_list.status_code == 200
    managed_item = next(item for item in managed_list.json() if item["id"] == agent["id"])
    assert managed_item["thumbnail_size"] == len(first_jpeg)
    assert managed_item["thumbnail_updated_at"] is not None

    ordinary = client.get("/api/agents/mine", headers=_headers(dev_token))
    ordinary_item = next(item for item in ordinary.json() if item["id"] == agent["id"])
    assert "thumbnail_size" not in ordinary_item
    assert "thumbnail_updated_at" not in ordinary_item

    denied = client.get(
        "/api/admin/managed-agents/{}/thumbnail".format(agent["id"]),
        headers=_headers(dev_token),
    )
    downloaded = client.get(
        "/api/admin/managed-agents/{}/thumbnail".format(agent["id"]),
        headers=_headers(admin_token),
    )
    assert denied.status_code == 403
    assert downloaded.status_code == 200
    assert downloaded.content == first_jpeg
    assert downloaded.headers["content-type"] == "image/jpeg"
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"

    audit = client.get(
        "/api/audit?action=managed_thumbnail.view", headers=_headers(admin_token)
    )
    assert audit.status_code == 200
    view = next(item for item in audit.json() if item["target_id"] == agent["id"])
    assert view["username"] == "admin"
    assert view["target_type"] == "agent"
    assert view["detail"] == "device=thumbnail-round-trip"

    second_jpeg = _image_bytes(color=(4, 5, 6))
    replaced = client.post(
        "/api/agents/{}/thumbnail".format(agent["id"]),
        content=second_jpeg,
        headers={**_headers(dev_token, agent["agent_token"]), "Content-Type": "image/jpeg"},
    )
    assert replaced.status_code == 200
    assert agent_thumbnails.thumbnail_path(agent["id"]).read_bytes() == second_jpeg
    assert [path.name for path in isolated_thumbnail_dir.iterdir()] == ["{}.jpg".format(agent["id"])]

    deleted = client.delete(
        "/api/agents/{}".format(agent["id"]), headers=_headers(admin_token)
    )
    assert deleted.status_code == 200
    assert not agent_thumbnails.thumbnail_path(agent["id"]).exists()


def test_thumbnail_upload_requires_owner_enabled_managed_agent_and_bound_device_token(
    client, admin_token, dev_token
):
    target = _register(client, dev_token, "thumbnail-auth-target")
    other = _register(client, dev_token, "thumbnail-auth-other")
    jpeg = _image_bytes()
    url = "/api/agents/{}/thumbnail".format(target["id"])

    no_user_jwt = client.post(
        url,
        content=jpeg,
        headers={"X-Agent-Token": target["agent_token"], "Content-Type": "image/jpeg"},
    )
    no_device_token = client.post(
        url,
        content=jpeg,
        headers={**_headers(dev_token), "Content-Type": "image/jpeg"},
    )
    wrong_device_token = client.post(
        url,
        content=jpeg,
        headers={**_headers(dev_token, other["agent_token"]), "Content-Type": "image/jpeg"},
    )
    wrong_owner = client.post(
        url,
        content=jpeg,
        headers={**_headers(admin_token, target["agent_token"]), "Content-Type": "image/jpeg"},
    )

    assert no_user_jwt.status_code == 401
    assert no_device_token.status_code == 401
    assert wrong_device_token.status_code == 403
    assert wrong_owner.status_code == 404

    impact = client.get(
        "/api/admin/managed-agents/{}/impact?action=disable".format(target["id"]),
        headers=_headers(admin_token),
    ).json()
    disabled = client.patch(
        "/api/admin/managed-agents/{}".format(target["id"]),
        json={"enabled": False, "impact_version": impact["version"]},
        headers=_headers(admin_token),
    )
    assert disabled.status_code == 200
    disabled_upload = client.post(
        url,
        content=jpeg,
        headers={**_headers(dev_token, target["agent_token"]), "Content-Type": "image/jpeg"},
    )
    assert disabled_upload.status_code == 404

    standard = _register(client, dev_token, "thumbnail-standard", mode="standard")
    standard_upload = client.post(
        "/api/agents/{}/thumbnail".format(standard["id"]),
        content=jpeg,
        headers={**_headers(dev_token), "Content-Type": "image/jpeg"},
    )
    assert standard_upload.status_code == 404


def test_device_pause_is_authoritative_and_old_protocol_omission_preserves_state(
    client, admin_token, dev_token
):
    registered = client.post(
        "/api/agents/register",
        json={
            "device_uid": "thumbnail-paused",
            "machine_name": "thumbnail-paused",
            "mode": "managed",
            "thumbnail_capture_paused": True,
        },
        headers=_headers(dev_token),
    )
    assert registered.status_code == 200
    agent = registered.json()
    assert agent["thumbnail_capture_paused"] is True

    # An older heartbeat omits the optional field and must not silently resume it.
    heartbeat = client.post(
        "/api/agents/{}/heartbeat".format(agent["id"]),
        json={},
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["thumbnail_capture_paused"] is True

    denied = client.post(
        "/api/agents/{}/thumbnail".format(agent["id"]),
        content=_image_bytes(),
        headers={**_headers(dev_token, agent["agent_token"]), "Content-Type": "image/jpeg"},
    )
    assert denied.status_code == 404

    managed = client.get("/api/admin/managed-agents", headers=_headers(admin_token)).json()
    assert next(item for item in managed if item["id"] == agent["id"])[
        "thumbnail_capture_paused"
    ] is True

    resumed = client.post(
        "/api/agents/{}/heartbeat".format(agent["id"]),
        json={"thumbnail_capture_paused": False},
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert resumed.status_code == 200
    assert resumed.json()["thumbnail_capture_paused"] is False


def test_pause_heartbeat_clears_latest_thumbnail_without_breaking_heartbeat(
    client, admin_token, dev_token, isolated_thumbnail_dir, monkeypatch
):
    agent = _register(client, dev_token, "thumbnail-clear-on-pause")
    uploaded = client.post(
        "/api/agents/{}/thumbnail".format(agent["id"]),
        content=_image_bytes(),
        headers={
            **_headers(dev_token, agent["agent_token"]),
            "Content-Type": "image/jpeg",
        },
    )
    assert uploaded.status_code == 200
    assert agent_thumbnails.thumbnail_path(agent["id"]).exists()

    paused = client.post(
        "/api/agents/{}/heartbeat".format(agent["id"]),
        json={"thumbnail_capture_paused": True},
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert paused.status_code == 200
    assert not agent_thumbnails.thumbnail_path(agent["id"]).exists()
    assert client.get(
        "/api/admin/managed-agents/{}/thumbnail".format(agent["id"]),
        headers=_headers(admin_token),
    ).status_code == 404

    # A filesystem cleanup problem is retried by later heartbeats and must not
    # turn liveness reporting into an error. Metadata is still cleared so the
    # stale image is no longer served.
    monkeypatch.setattr(
        "app.routers.agents.delete_thumbnail",
        lambda _agent_id: (_ for _ in ()).throw(OSError("locked")),
    )
    failed_cleanup = client.post(
        "/api/agents/{}/heartbeat".format(agent["id"]),
        json={"thumbnail_capture_paused": True},
        headers=_headers(dev_token, agent["agent_token"]),
    )
    assert failed_cleanup.status_code == 200
    managed = client.get(
        "/api/admin/managed-agents", headers=_headers(admin_token),
    ).json()
    row = next(item for item in managed if item["id"] == agent["id"])
    assert row["thumbnail_updated_at"] is None
    assert row["thumbnail_size"] is None


def test_thumbnail_upload_rejects_wrong_type_corrupt_oversize_and_oversized_dimensions(
    client, dev_token
):
    agent = _register(client, dev_token, "thumbnail-validation")
    url = "/api/agents/{}/thumbnail".format(agent["id"])
    auth = _headers(dev_token, agent["agent_token"])

    wrong_media_type = client.post(
        url, content=_image_bytes(), headers={**auth, "Content-Type": "application/octet-stream"}
    )
    disguised_png = client.post(
        url, content=_image_bytes("PNG"), headers={**auth, "Content-Type": "image/jpeg"}
    )
    corrupt = client.post(
        url, content=b"\xff\xd8not-a-jpeg\xff\xd9", headers={**auth, "Content-Type": "image/jpeg"}
    )
    oversize = client.post(
        url,
        content=b"\xff\xd8" + (b"x" * (1024 * 1024)) + b"\xff\xd9",
        headers={**auth, "Content-Type": "image/jpeg"},
    )
    dimensions = client.post(
        url,
        content=_image_bytes(size=(1281, 1)),
        headers={**auth, "Content-Type": "image/jpeg"},
    )

    assert wrong_media_type.status_code == 415
    assert disguised_png.status_code == 415
    assert corrupt.status_code == 415
    assert oversize.status_code == 413
    assert dimensions.status_code == 400
    assert not agent_thumbnails.thumbnail_path(agent["id"]).exists()
