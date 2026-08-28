from client.ui import wizard
from client.ui.wizard import WIZARD_HTML, WizardApi


def test_wizard_is_localized_in_chinese():
    required = [
        "初始化设置", "服务端地址", "用户名", "密码", "脚本下载目录",
        "结果输出目录", "默认浏览器", "代理地址（可选）", "完成设置",
    ]
    for text in required:
        assert text in WIZARD_HTML

    obsolete_english = [
        "Initial Setup", "Server Address", "Test Login", "Login failed",
        "Cannot connect to server", "Default (no override)", "Finish</button>",
    ]
    for text in obsolete_english:
        assert text not in WIZARD_HTML


def test_wizard_displays_login_and_save_errors_and_requires_verification():
    assert "请输入用户名和密码" in WIZARD_HTML
    assert "登录失败（HTTP " in WIZARD_HTML
    assert "无法连接服务端，请检查地址和网络" in WIZARD_HTML
    assert "账号信息尚未通过验证，请先测试登录" in WIZARD_HTML
    assert "保存设置失败" in WIZARD_HTML
    assert "if (loginVerified || await testLogin())" in WIZARD_HTML
    assert "if (!loginVerified)" in WIZARD_HTML
    assert "window.pywebview.api.testLogin" in WIZARD_HTML
    assert "fetch(url + '/api/auth/login'" not in WIZARD_HTML


def test_wizard_login_uses_native_bridge_to_avoid_browser_cors(monkeypatch):
    class Response:
        ok = True
        status_code = 200

    calls = []
    monkeypatch.setattr(
        wizard.requests,
        "post",
        lambda url, json, timeout: calls.append((url, json, timeout)) or Response(),
    )

    result = WizardApi().testLogin("http://192.168.1.106:8123/", "employee", "secret")

    assert result == {"ok": True, "status": 200, "detail": ""}
    assert calls == [
        (
            "http://192.168.1.106:8123/api/auth/login",
            {"username": "employee", "password": "secret"},
            10,
        )
    ]
