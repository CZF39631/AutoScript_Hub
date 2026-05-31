def test_list_users_admin(client, admin_token):
    resp = client.get("/api/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_users_forbidden_for_operator(client, op_token):
    resp = client.get("/api/users", headers={"Authorization": f"Bearer {op_token}"})
    assert resp.status_code == 403


def test_create_user(client, admin_token):
    resp = client.post(
        "/api/users",
        json={"username": "newuser", "password": "pass123", "display_name": "New User", "role": "operator"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "newuser"
    assert data["role"] == "operator"


def test_create_duplicate_user(client, admin_token):
    client.post(
        "/api/users",
        json={"username": "dup", "password": "pass", "display_name": "Dup", "role": "operator"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = client.post(
        "/api/users",
        json={"username": "dup", "password": "pass", "display_name": "Dup", "role": "operator"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400


def test_update_user(client, admin_token):
    create_resp = client.post(
        "/api/users",
        json={"username": "updateme", "password": "pass", "display_name": "Old Name", "role": "operator"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    uid = create_resp.json()["id"]
    resp = client.put(
        f"/api/users/{uid}",
        json={"display_name": "New Name", "status": "disabled"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "New Name"
    assert resp.json()["status"] == "disabled"
