"""First-run setup wizard using pywebview."""
import json
import os
import sys

import webview

from client.ui.config_manager import save_config

WIZARD_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AutoScript Hub - Setup</title>
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
  <h2>AutoScript Hub - Initial Setup</h2>
  <div class="steps">
    <div class="step active" id="s1">Server</div>
    <div class="step" id="s2">Account</div>
    <div class="step" id="s3">Paths</div>
    <div class="step" id="s4">Browser</div>
    <div class="step" id="s5">Network</div>
  </div>

  <!-- Step 1: Server -->
  <div class="panel active" id="p1">
    <label>Server Address</label>
    <input id="server_url" value="http://127.0.0.1:8000" placeholder="http://192.168.1.100:8000">
    <div class="msg" id="m1"></div>
    <div class="btn-row">
      <button class="primary" onclick="goStep(2)">Next</button>
    </div>
  </div>

  <!-- Step 2: Account -->
  <div class="panel" id="p2">
    <label>Username</label>
    <input id="username" placeholder="admin">
    <label>Password</label>
    <input id="password" type="password" placeholder="password">
    <div class="msg" id="m2"></div>
    <div class="btn-row">
      <button onclick="goStep(1)">Back</button>
      <button onclick="testLogin()">Test Login</button>
      <button class="primary" onclick="goStep(3)">Next</button>
    </div>
  </div>

  <!-- Step 3: Paths -->
  <div class="panel" id="p3">
    <label>Script Download Directory</label>
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <input id="script_dir" style="margin-bottom:0" placeholder="D:\\scripts">
      <button onclick="pickFolder('script_dir')">Browse</button>
    </div>
    <label>Output Directory</label>
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <input id="output_dir" style="margin-bottom:0" placeholder="D:\\output">
      <button onclick="pickFolder('output_dir')">Browse</button>
    </div>
    <div class="hint">Leave empty to use default paths</div>
    <div class="btn-row">
      <button onclick="goStep(2)">Back</button>
      <button class="primary" onclick="goStep(4)">Next</button>
    </div>
  </div>

  <!-- Step 4: Browser -->
  <div class="panel" id="p4">
    <label>Default Browser</label>
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <select id="browser_path" style="margin-bottom:0"><option value="">Default (no override)</option></select>
      <button onclick="detectBrowsers()">Detect</button>
    </div>
    <label>Debug Port</label>
    <input id="browser_port" type="number" value="9222" placeholder="9222">
    <div class="btn-row">
      <button onclick="goStep(3)">Back</button>
      <button class="primary" onclick="goStep(5)">Next</button>
    </div>
  </div>

  <!-- Step 5: Proxy -->
  <div class="panel" id="p5">
    <label>Proxy Address (optional)</label>
    <input id="proxy" placeholder="http://127.0.0.1:7890">
    <div class="hint">Leave empty if not needed</div>
    <div class="msg" id="m5"></div>
    <div class="btn-row">
      <button onclick="goStep(4)">Back</button>
      <button class="primary" onclick="finish()">Finish</button>
    </div>
  </div>
</div>

<script>
var currentStep = 1;

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

async function testLogin() {
  var url = document.getElementById('server_url').value;
  var user = document.getElementById('username').value;
  var pass = document.getElementById('password').value;
  if (!user || !pass) { showMsg('m2', 'Please enter username and password', false); return; }
  try {
    var resp = await fetch(url + '/api/auth/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: user, password: pass})
    });
    if (resp.ok) { showMsg('m2', 'Login successful!', true); }
    else { var d = await resp.json(); showMsg('m2', d.detail || 'Login failed', false); }
  } catch(e) { showMsg('m2', 'Cannot connect to server: ' + e.message, false); }
}

async function detectBrowsers() {
  try {
    var browsers;
    if (window.pywebview && window.pywebview.api) {
      browsers = await window.pywebview.api.detectBrowsers();
    } else {
      var resp = await fetch('http://127.0.0.1:18080/detect-browsers');
      browsers = await resp.json();
    }
    var sel = document.getElementById('browser_path');
    sel.innerHTML = '<option value="">Default (no override)</option>';
    browsers.forEach(function(b) {
      var opt = document.createElement('option');
      opt.value = b.path;
      opt.textContent = b.name + ' - ' + b.path;
      sel.appendChild(opt);
    });
  } catch(e) { alert('Detection failed, ensure Agent is running'); }
}

async function pickFolder(inputId) {
  if (window.pywebview && window.pywebview.api) {
    var path = await window.pywebview.api.openFolderDialog();
    if (path) document.getElementById(inputId).value = path;
  }
}

async function finish() {
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
  if (window.pywebview && window.pywebview.api) {
    await window.pywebview.api.saveAndFinish(JSON.stringify(config));
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
        "AutoScript Hub - Initial Setup",
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
