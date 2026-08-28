"""First-run setup wizard using pywebview."""
import json
import os
import sys

import webview

from client.ui.config_manager import save_config

WIZARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>AutoScript Hub - 初始化设置</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', sans-serif; background: #f5f5f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
.card { background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; width: 520px; }
h2 { color: #1890ff; margin-bottom: 24px; font-size: 20px; }
.steps { display: flex; margin-bottom: 24px; }
.step { flex: 1; text-align: center; padding: 8px 0; font-size: 13px; color: #999; border-bottom: 2px solid #f0f0f0; }
.step.active { color: #1890ff; border-bottom-color: #1890ff; font-weight: 600; }
.step.done { color: #52c41a; border-bottom-color: #52c41a; }
.panel { display: none; }
.panel.active { display: block; }
label { display: block; margin-bottom: 4px; font-size: 14px; color: #333; font-weight: 500; }
input, select { width: 100%; padding: 8px 12px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 14px; margin-bottom: 16px; }
input:focus, select:focus { outline: none; border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24,144,255,0.2); }
.btn-row { display: flex; gap: 8px; margin-top: 20px; }
button { padding: 8px 24px; border-radius: 6px; border: 1px solid #d9d9d9; background: #fff; cursor: pointer; font-size: 14px; }
button:hover { border-color: #1890ff; color: #1890ff; }
button.primary { background: #1890ff; color: #fff; border-color: #1890ff; }
button.primary:hover { background: #40a9ff; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.msg { padding: 8px 12px; border-radius: 4px; margin-bottom: 12px; font-size: 13px; display: none; }
.msg.error { display: block; background: #fff2f0; color: #ff4d4f; border: 1px solid #ffccc7; }
.msg.ok { display: block; background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
.hint { font-size: 12px; color: #999; margin-top: -12px; margin-bottom: 12px; }
</style>
</head>
<body>
<div class="card">
  <h2>AutoScript Hub 初始化设置</h2>
  <div class="steps">
    <div class="step active" id="s1">服务端</div>
    <div class="step" id="s2">账号</div>
    <div class="step" id="s3">目录</div>
    <div class="step" id="s4">浏览器</div>
    <div class="step" id="s5">网络</div>
  </div>

  <!-- Step 1: Server -->
  <div class="panel active" id="p1">
    <label>服务端地址</label>
    <input id="server_url" value="http://127.0.0.1:8000" placeholder="例如：http://192.168.1.100:8000">
    <div class="msg" id="m1"></div>
    <div class="btn-row">
      <button class="primary" onclick="goAccountStep()">下一步</button>
    </div>
  </div>

  <!-- Step 2: Account -->
  <div class="panel" id="p2">
    <label>用户名</label>
    <input id="username" placeholder="请输入用户名" oninput="invalidateLogin()">
    <label>密码</label>
    <input id="password" type="password" placeholder="请输入密码" oninput="invalidateLogin()">
    <div class="msg" id="m2"></div>
    <div class="btn-row">
      <button onclick="goStep(1)">上一步</button>
      <button id="login_test" onclick="testLogin()">测试登录</button>
      <button class="primary" onclick="continueAfterLogin()">下一步</button>
    </div>
  </div>

  <!-- Step 3: Paths -->
  <div class="panel" id="p3">
    <label>脚本下载目录</label>
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <input id="script_dir" style="margin-bottom:0" placeholder="D:\\scripts">
      <button onclick="pickFolder('script_dir')">浏览…</button>
    </div>
    <label>结果输出目录</label>
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <input id="output_dir" style="margin-bottom:0" placeholder="D:\\output">
      <button onclick="pickFolder('output_dir')">浏览…</button>
    </div>
    <div class="hint">留空将使用默认目录</div>
    <div class="btn-row">
      <button onclick="goStep(2)">上一步</button>
      <button class="primary" onclick="goStep(4)">下一步</button>
    </div>
  </div>

  <!-- Step 4: Browser -->
  <div class="panel" id="p4">
    <label>默认浏览器</label>
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <select id="browser_path" style="margin-bottom:0"><option value="">使用系统默认浏览器</option></select>
      <button onclick="detectBrowsers()">检测浏览器</button>
    </div>
    <label>浏览器调试端口</label>
    <input id="browser_port" type="number" value="9222" placeholder="9222">
    <div class="btn-row">
      <button onclick="goStep(3)">上一步</button>
      <button class="primary" onclick="goStep(5)">下一步</button>
    </div>
  </div>

  <!-- Step 5: Proxy -->
  <div class="panel" id="p5">
    <label>代理地址（可选）</label>
    <input id="proxy" placeholder="例如：http://127.0.0.1:7890">
    <div class="hint">不需要代理时请留空</div>
    <div class="msg" id="m5"></div>
    <div class="btn-row">
      <button onclick="goStep(4)">上一步</button>
      <button class="primary" onclick="finish()">完成设置</button>
    </div>
  </div>
</div>

<script>
var currentStep = 1;
var loginVerified = false;

function showMsg(id, text, ok) {
  var el = document.getElementById(id);
  el.className = 'msg ' + (ok ? 'ok' : 'error');
  el.textContent = text;
}

function goStep(n) {
  document.getElementById('p' + currentStep).className = 'panel';
  document.getElementById('s' + currentStep).className = currentStep < n ? 'step done' : 'step';
  currentStep = n;
  document.getElementById('p' + n).className = 'panel active';
  document.getElementById('s' + n).className = 'step active';
}

function invalidateLogin() {
  loginVerified = false;
}

function goAccountStep() {
  var url = document.getElementById('server_url').value.trim();
  if (!/^https?:\/\/[^\s]+$/i.test(url)) {
    showMsg('m1', '请输入有效的服务端地址，必须以 http:// 或 https:// 开头', false);
    return;
  }
  invalidateLogin();
  goStep(2);
}

async function testLogin() {
  var url = document.getElementById('server_url').value.trim().replace(/\/$/, '');
  var user = document.getElementById('username').value.trim();
  var pass = document.getElementById('password').value;
  var button = document.getElementById('login_test');
  loginVerified = false;
  if (!user || !pass) {
    showMsg('m2', '请输入用户名和密码', false);
    return false;
  }
  button.disabled = true;
  button.textContent = '正在验证…';
  showMsg('m2', '正在连接服务端并验证账号…', true);
  try {
    var resp = await fetch(url + '/api/auth/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: user, password: pass})
    });
    var data = {};
    try { data = await resp.json(); } catch (_) {}
    if (resp.ok) {
      loginVerified = true;
      showMsg('m2', '登录验证成功', true);
      return true;
    }
    var detail = typeof data.detail === 'string' ? data.detail : '';
    showMsg('m2', detail || ('登录失败（HTTP ' + resp.status + '）'), false);
    return false;
  } catch(e) {
    showMsg('m2', '无法连接服务端，请检查地址和网络。错误：' + e.message, false);
    return false;
  } finally {
    button.disabled = false;
    button.textContent = '测试登录';
  }
}

async function continueAfterLogin() {
  if (loginVerified || await testLogin()) {
    goStep(3);
  }
}

async function detectBrowsers() {
  try {
    var browsers;
    if (!window.pywebview || !window.pywebview.api) {
      throw new Error('本地功能接口不可用');
    }
    browsers = await window.pywebview.api.detectBrowsers();
    var sel = document.getElementById('browser_path');
    sel.innerHTML = '<option value="">使用系统默认浏览器</option>';
    browsers.forEach(function(b) {
      var opt = document.createElement('option');
      opt.value = b.path;
      opt.textContent = b.name + ' - ' + b.path;
      sel.appendChild(opt);
    });
  } catch(e) { alert('浏览器检测失败：' + e.message); }
}

async function pickFolder(inputId) {
  if (window.pywebview && window.pywebview.api) {
    var path = await window.pywebview.api.openFolderDialog();
    if (path) document.getElementById(inputId).value = path;
  }
}

async function finish() {
  if (!loginVerified) {
    goStep(2);
    showMsg('m2', '账号信息尚未通过验证，请先测试登录', false);
    return;
  }
  var config = {
    server_url: document.getElementById('server_url').value,
    username: document.getElementById('username').value,
    password: document.getElementById('password').value,
    script_download_dir: document.getElementById('script_dir').value,
    output_dir: document.getElementById('output_dir').value,
    default_browser_path: document.getElementById('browser_path').value,
    browser_debug_port: parseInt(document.getElementById('browser_port').value) || 9222,
    proxy: document.getElementById('proxy').value,
    setup_completed: true
  };
  if (!window.pywebview || !window.pywebview.api) {
    showMsg('m5', '无法保存设置：本地功能接口不可用', false);
    return;
  }
  try {
    await window.pywebview.api.saveAndFinish(JSON.stringify(config));
  } catch (e) {
    showMsg('m5', '保存设置失败：' + e.message, false);
  }
}
</script>
</body>
</html>"""


class WizardApi:
    """JS bridge for the setup wizard."""

    def openFolderDialog(self):
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None

    def detectBrowsers(self):
        from client.agent.local_server import _detect_browsers
        return _detect_browsers()

    def saveAndFinish(self, config_json):
        config = json.loads(config_json)
        save_config(config)
        webview.windows[0].destroy()


def run_wizard():
    """Run the first-run setup wizard. Blocks until complete."""
    api = WizardApi()
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wizard.html")
    # Write HTML to temp file for pywebview to load
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(WIZARD_HTML)

    window = webview.create_window(
        "AutoScript Hub - 初始化设置",
        html_path,
        js_api=api,
        width=600,
        height=520,
        resizable=False,
    )
    webview.start()

    # Cleanup temp html
    try:
        os.remove(html_path)
    except OSError:
        pass
