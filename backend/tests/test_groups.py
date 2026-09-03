import json
import os

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_script.py")


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_group(client, admin_token, name, **extra):
    payload = {"name": name, "description": f"{name}说明", **extra}
    response = client.post("/api/groups", json=payload, headers=headers(admin_token))
    assert response.status_code == 200, response.text
    return response.json()


def create_user_and_login(client, admin_token, username, role, group_ids):
    response = client.post(
        "/api/users",
        json={
            "username": username,
            "password": "pass1234",
            "display_name": username,
            "role": role,
            "group_ids": group_ids,
        },
        headers=headers(admin_token),
    )
    assert response.status_code == 200, response.text
    token = client.post(
        "/api/auth/login", json={"username": username, "password": "pass1234"},
    ).json()["token"]
    return response.json(), token


def upload(client, token, group_ids):
    with open(FIXTURE, "rb") as stream:
        return client.post(
            "/api/scripts/upload",
            files={"file": ("sample.py", stream, "text/x-python")},
            data={"changelog": "分组测试", "group_ids": json.dumps(group_ids)},
            headers=headers(token),
        )


def test_admin_manages_groups_and_default_group(client, admin_token, op_token):
    default_groups = client.get("/api/groups", headers=headers(admin_token)).json()
    assert len(default_groups) == 1
    assert default_groups[0]["is_default"] is True

    created = create_group(client, admin_token, "业务组A")
    assert created["user_count"] == 0
    assert client.get("/api/groups", headers=headers(op_token)).status_code == 403

    updated = client.put(
        f"/api/groups/{created['id']}",
        json={"description": "新的说明", "is_default": True},
        headers=headers(admin_token),
    )
    assert updated.status_code == 200
    assert updated.json()["is_default"] is True
    assert sum(item["is_default"] for item in client.get("/api/groups", headers=headers(admin_token)).json()) == 1

    old_default = next(item for item in default_groups if item["is_default"])
    assert client.delete(f"/api/groups/{old_default['id']}", headers=headers(admin_token)).status_code == 409
    unused = create_group(client, admin_token, "未使用组")
    assert client.delete(f"/api/groups/{unused['id']}", headers=headers(admin_token)).status_code == 200
    assert client.delete(f"/api/groups/{created['id']}", headers=headers(admin_token)).status_code == 400


def test_new_user_uses_default_group_and_can_be_filtered(client, admin_token):
    group = create_group(client, admin_token, "新默认组", is_default=True)
    response = client.post(
        "/api/users",
        json={"username": "default_member", "password": "pass1234", "display_name": "默认成员", "role": "operator"},
        headers=headers(admin_token),
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["groups"]] == [group["id"]]

    filtered = client.get(f"/api/users?group_id={group['id']}", headers=headers(admin_token))
    assert [item["username"] for item in filtered.json()] == ["default_member"]


def test_marketplace_is_partitioned_and_direct_id_routes_are_protected(client, admin_token):
    group_a = create_group(client, admin_token, "市场A")
    group_b = create_group(client, admin_token, "市场B")
    _, token_a = create_user_and_login(client, admin_token, "operator_a", "operator", [group_a["id"]])
    _, token_b = create_user_and_login(client, admin_token, "operator_b", "operator", [group_b["id"]])

    script_a = upload(client, admin_token, [group_a["id"]]).json()
    script_b = upload(client, admin_token, [group_b["id"]]).json()
    shared = upload(client, admin_token, [group_a["id"], group_b["id"]]).json()

    ids_a = {item["id"] for item in client.get("/api/scripts/marketplace", headers=headers(token_a)).json()}
    ids_b = {item["id"] for item in client.get("/api/scripts/marketplace", headers=headers(token_b)).json()}
    assert ids_a == {script_a["id"], shared["id"]}
    assert ids_b == {script_b["id"], shared["id"]}
    assert set(client.get("/api/scripts/authorized-ids", headers=headers(token_a)).json()) == ids_a
    shared_for_a = client.get(f"/api/scripts/{shared['id']}", headers=headers(token_a)).json()
    assert [item["id"] for item in shared_for_a["groups"]] == [group_a["id"]]
    shared_for_admin = client.get(f"/api/scripts/{shared['id']}", headers=headers(admin_token)).json()
    assert {item["id"] for item in shared_for_admin["groups"]} == {group_a["id"], group_b["id"]}

    hidden_id = script_a["id"]
    assert client.get(f"/api/scripts/{hidden_id}", headers=headers(token_b)).status_code == 404
    assert client.get(f"/api/scripts/{hidden_id}/versions", headers=headers(token_b)).status_code == 404
    assert client.get(f"/api/scripts/{hidden_id}/download", headers=headers(token_b)).status_code == 404
    assert client.get(f"/api/scripts/{hidden_id}/presets", headers=headers(token_b)).status_code == 404
    assert client.post(f"/api/scripts/{hidden_id}/install", headers=headers(token_b)).status_code == 404
    assert client.post(
        "/api/runs/execute",
        json={"script_id": hidden_id, "params": {"url_file": "C:/test.txt"}},
        headers=headers(token_b),
    ).status_code == 404


def test_membership_removal_revokes_market_install_and_execute(client, admin_token):
    group_a = create_group(client, admin_token, "撤权A")
    group_b = create_group(client, admin_token, "撤权B")
    user, token = create_user_and_login(client, admin_token, "revoked_user", "operator", [group_a["id"]])
    script = upload(client, admin_token, [group_a["id"]]).json()

    assert client.post(f"/api/scripts/{script['id']}/install", headers=headers(token)).status_code == 200
    assert [item["id"] for item in client.get("/api/scripts", headers=headers(token)).json()] == [script["id"]]

    assert client.put(
        f"/api/users/{user['id']}", json={"group_ids": [group_b["id"]]}, headers=headers(admin_token),
    ).status_code == 200
    assert client.get("/api/scripts", headers=headers(token)).json() == []
    assert client.post(
        "/api/runs/execute",
        json={"script_id": script["id"], "params": {"url_file": "C:/test.txt"}},
        headers=headers(token),
    ).status_code == 404
    assert client.post(f"/api/scripts/{script['id']}/uninstall", headers=headers(token)).status_code == 200


def test_developer_can_only_publish_and_manage_own_groups(client, admin_token):
    group_a = create_group(client, admin_token, "开发A")
    group_b = create_group(client, admin_token, "开发B")
    _, dev_a = create_user_and_login(client, admin_token, "developer_a", "developer", [group_a["id"]])
    _, dev_b = create_user_and_login(client, admin_token, "developer_b", "developer", [group_b["id"]])
    assert [item["id"] for item in client.get("/api/groups/available", headers=headers(dev_a)).json()] == [group_a["id"]]

    script = upload(client, dev_a, [group_a["id"]])
    assert script.status_code == 200
    script_id = script.json()["id"]
    assert upload(client, dev_a, [group_b["id"]]).status_code == 403

    with open(FIXTURE, "rb") as stream:
        response = client.post(
            f"/api/scripts/{script_id}/upload-version",
            files={"file": ("sample.py", stream, "text/x-python")},
            headers=headers(dev_b),
        )
    assert response.status_code == 404
    assert client.post(f"/api/scripts/{script_id}/disable", headers=headers(dev_b)).status_code == 404
    assert client.put(
        f"/api/scripts/{script_id}/groups",
        json={"group_ids": [group_a["id"], group_b["id"]]},
        headers=headers(dev_a),
    ).status_code == 403


def test_disabled_group_removes_non_admin_access(client, admin_token):
    group = create_group(client, admin_token, "停用组")
    _, token = create_user_and_login(client, admin_token, "disabled_group_user", "operator", [group["id"]])
    script = upload(client, admin_token, [group["id"]]).json()

    assert client.get(f"/api/scripts/{script['id']}", headers=headers(token)).status_code == 200
    response = client.put(
        f"/api/groups/{group['id']}", json={"status": "disabled"}, headers=headers(admin_token),
    )
    assert response.status_code == 200
    assert client.get("/api/scripts/marketplace", headers=headers(token)).json() == []
    assert client.get(f"/api/scripts/{script['id']}", headers=headers(token)).status_code == 404


def test_developer_run_history_is_limited_to_accessible_groups(client, admin_token):
    group_a = create_group(client, admin_token, "运行A")
    group_b = create_group(client, admin_token, "运行B")
    _, dev_a = create_user_and_login(client, admin_token, "run_developer_a", "developer", [group_a["id"]])
    _, op_a = create_user_and_login(client, admin_token, "run_operator_a", "operator", [group_a["id"]])
    _, op_b = create_user_and_login(client, admin_token, "run_operator_b", "operator", [group_b["id"]])
    script_a = upload(client, admin_token, [group_a["id"]]).json()
    script_b = upload(client, admin_token, [group_b["id"]]).json()
    shared = upload(client, admin_token, [group_a["id"], group_b["id"]]).json()

    run_a = client.post(
        "/api/runs/execute",
        json={"script_id": script_a["id"], "params": {"url_file": "C:/a.txt"}},
        headers=headers(op_a),
    ).json()
    run_b = client.post(
        "/api/runs/execute",
        json={"script_id": script_b["id"], "params": {"url_file": "C:/b.txt"}},
        headers=headers(op_b),
    ).json()

    assert client.post(f"/api/runs/{run_b['id']}/cancel", headers=headers(op_b)).status_code == 200
    shared_run_b = client.post(
        "/api/runs/execute",
        json={"script_id": shared["id"], "params": {"url_file": "C:/shared-b.txt"}},
        headers=headers(op_b),
    ).json()
    issue_b = client.post(
        "/api/issues",
        json={"run_id": shared_run_b["id"], "title": "B组共享脚本工单"},
        headers=headers(op_b),
    ).json()

    visible_ids = {item["id"] for item in client.get("/api/runs", headers=headers(dev_a)).json()}
    assert run_a["id"] in visible_ids
    assert run_b["id"] not in visible_ids
    assert shared_run_b["id"] not in visible_ids
    assert client.get(f"/api/runs/{run_b['id']}", headers=headers(dev_a)).status_code == 404
    assert client.get(f"/api/runs/{shared_run_b['id']}/log", headers=headers(dev_a)).status_code == 404
    issue_ids = {item["id"] for item in client.get("/api/issues", headers=headers(dev_a)).json()}
    assert issue_b["id"] not in issue_ids
    assert client.post(
        f"/api/issues/{issue_b['id']}/resolve",
        json={"resolve_note": "不应允许跨组处理"},
        headers=headers(dev_a),
    ).status_code == 404


def test_execute_rejects_another_users_environment(client, admin_token):
    group = create_group(client, admin_token, "环境组")
    _, token_a = create_user_and_login(client, admin_token, "env_user_a", "operator", [group["id"]])
    _, token_b = create_user_and_login(client, admin_token, "env_user_b", "operator", [group["id"]])
    script = upload(client, admin_token, [group["id"]]).json()
    environment = client.post(
        "/api/environments", json={"name": "B的环境"}, headers=headers(token_b),
    ).json()

    response = client.post(
        "/api/runs/execute",
        json={
            "script_id": script["id"],
            "params": {"url_file": "C:/a.txt"},
            "environment_id": environment["id"],
        },
        headers=headers(token_a),
    )
    assert response.status_code == 404


def test_group_delete_is_blocked_while_associations_exist(client, admin_token):
    group = create_group(client, admin_token, "关联组")
    create_user_and_login(client, admin_token, "linked_user", "operator", [group["id"]])
    response = client.delete(f"/api/groups/{group['id']}", headers=headers(admin_token))
    assert response.status_code == 409
    assert "关联" in response.json()["detail"]
