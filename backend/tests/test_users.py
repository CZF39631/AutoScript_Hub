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


def test_search_users_by_username_or_display_name(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    client.post("/api/users", json={
        "username": "search_alice", "password": "pass1234",
        "display_name": "财务专员", "role": "operator",
    }, headers=headers)
    client.post("/api/users", json={
        "username": "other_user", "password": "pass1234",
        "display_name": "其他用户", "role": "operator",
    }, headers=headers)

    by_username = client.get("/api/users?search=ALICE", headers=headers)
    by_display_name = client.get("/api/users?search=财务", headers=headers)

    assert [item["username"] for item in by_username.json()] == ["search_alice"]
    assert [item["username"] for item in by_display_name.json()] == ["search_alice"]


def test_admin_can_change_user_role(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post("/api/users", json={
        "username": "role_user", "password": "pass1234",
        "display_name": "Role User", "role": "operator",
    }, headers=headers).json()

    response = client.put(
        f"/api/users/{created['id']}", json={"role": "developer"}, headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["role"] == "developer"


def test_invalid_role_and_status_are_rejected(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post("/api/users", json={
        "username": "validated_user", "password": "pass1234",
        "display_name": "Validated", "role": "operator",
    }, headers=headers).json()

    assert client.put(
        f"/api/users/{created['id']}", json={"role": "root"}, headers=headers,
    ).status_code == 422
    assert client.put(
        f"/api/users/{created['id']}", json={"status": "unknown"}, headers=headers,
    ).status_code == 422


def test_delete_user_is_soft_delete_and_removes_login_access(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post("/api/users", json={
        "username": "delete_me", "password": "pass1234",
        "display_name": "Delete Me", "role": "operator",
    }, headers=headers).json()

    response = client.delete(f"/api/users/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert all(item["id"] != created["id"] for item in client.get("/api/users", headers=headers).json())
    assert client.post(
        "/api/auth/login", json={"username": "delete_me", "password": "pass1234"},
    ).status_code == 401


def test_admin_cannot_delete_disable_or_demote_self(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    admin = next(item for item in client.get("/api/users", headers=headers).json() if item["username"] == "admin")

    assert client.delete(f"/api/users/{admin['id']}", headers=headers).status_code == 400
    assert client.put(
        f"/api/users/{admin['id']}", json={"status": "disabled"}, headers=headers,
    ).status_code == 400
    assert client.put(
        f"/api/users/{admin['id']}", json={"role": "operator"}, headers=headers,
    ).status_code == 400


def test_operator_cannot_delete_user(client, op_token):
    response = client.delete(
        "/api/users/1", headers={"Authorization": f"Bearer {op_token}"},
    )
    assert response.status_code == 403
