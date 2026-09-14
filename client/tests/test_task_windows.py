"""真实 Windows Job 集成：仅运行临时目录中的合成 sleep 进程。"""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from client.runtime.process_tree import spawn_contained, stop_process_tree

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows Job integration')


def wait_file(path, proc, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists() and path.stat().st_size:
            return path.read_text()
        if proc.poll() is not None:
            raise AssertionError('synthetic process exited before handshake')
        time.sleep(.02)
    raise AssertionError('synthetic handshake timed out')


def process_handle(pid):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    assert handle, ctypes.get_last_error()
    return kernel, handle


def test_real_windows_user_code_starts_inside_job(tmp_path):
    output = tmp_path / 'contained.txt'
    code = ("import ctypes,time,pathlib; value=ctypes.c_int(); k=ctypes.WinDLL('kernel32',use_last_error=True); "
            "k.GetCurrentProcess.restype=ctypes.c_void_p; "
            "k.IsProcessInJob.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)]; "
            "assert k.IsProcessInJob(k.GetCurrentProcess(),None,ctypes.byref(value)); "
            "pathlib.Path({!r}).write_text(str(value.value)); time.sleep(60)").format(str(output))
    proc = spawn_contained([sys.executable, '-c', code], cwd=tmp_path)
    try:
        assert wait_file(output, proc) == '1'
    finally:
        stop_process_tree(proc)


def test_real_windows_parent_exit_still_cleans_descendants(tmp_path):
    output = tmp_path / 'descendant.txt'
    code = "import subprocess,sys,pathlib,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); pathlib.Path({!r}).write_text(str(p.pid)); time.sleep(.5)".format(str(output))
    proc = spawn_contained([sys.executable, '-c', code], cwd=tmp_path)
    kernel = handle = None
    try:
        pid = int(wait_file(output, proc))
        kernel, handle = process_handle(pid)
        proc.wait(timeout=10)
        assert kernel.WaitForSingleObject(handle, 0) == 258  # descendant still running
        stop_process_tree(proc)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        if getattr(proc._process_tree, 'handle', None):
            stop_process_tree(proc)
        if handle:
            kernel.CloseHandle(handle)


def test_real_windows_agent_abnormal_exit_kills_job(tmp_path):
    output, release = tmp_path / 'child.txt', tmp_path / 'release.txt'
    root = str(Path(__file__).resolve().parents[2])
    code = ("import os,sys,time,pathlib; sys.path.insert(0,{!r}); "
            "from client.runtime.process_tree import spawn_contained; "
            "p=spawn_contained([sys.executable,'-c','import time;time.sleep(60)']); "
            "pathlib.Path({!r}).write_text(str(p.pid));\n"
            "while not pathlib.Path({!r}).exists(): time.sleep(.02)\n"
            "os._exit(17)\n").format(root, str(output), str(release))
    helper = subprocess.Popen([sys.executable, '-c', code], cwd=tmp_path)
    kernel = handle = None
    try:
        kernel, handle = process_handle(int(wait_file(output, helper)))
        release.write_text('stop only this synthetic helper')
        assert helper.wait(timeout=10) == 17
        assert kernel.WaitForSingleObject(handle, 10000) == 0
    finally:
        if helper.poll() is None:
            helper.kill()
            helper.wait(timeout=10)
        if handle:
            kernel.CloseHandle(handle)
