"""Fail-closed process containment. Windows jobs are assigned before user code runs."""
import ctypes
import os
import signal
import subprocess
import time
import hashlib


def containment_name(paths, kind):
    scope = str(paths.runs_dir.resolve()).casefold().encode('utf-8')
    return 'Local\\AutoScriptHub-' + hashlib.sha256(scope).hexdigest()[:32] + '-' + kind


class StopUnconfirmed(RuntimeError):
    """The execution slot must remain occupied until containment is verified empty."""


class ProcessTree:
    def __init__(self, name=None):
        self.handle = None
        self.pid = None
        if os.name == 'nt':
            from ctypes import wintypes as w
            class Basic(ctypes.Structure):
                _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                            ('flags', w.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                            ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
            class IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
            class Extended(ctypes.Structure):
                _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                            ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
            self.kernel.CreateJobObjectW.restype = w.HANDLE
            self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
            self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
            self.kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
            self.kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
            self.kernel.CloseHandle.argtypes = [w.HANDLE]
            self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
            self.kernel.OpenProcess.restype = w.HANDLE
            self.handle = self.kernel.CreateJobObjectW(None, name)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())

    def attach(self, pid):
        self.pid = pid
        if os.name == 'nt':
            process = self.kernel.OpenProcess(0x0100 | 0x0001, False, pid)
            if not process:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not self.kernel.AssignProcessToJobObject(self.handle, process):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self.kernel.CloseHandle(process)

    def stop(self):
        if os.name == 'nt':
            if self.handle and not self.kernel.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
        elif self.pid:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def confirm_stopped(self, timeout=10):
        """TerminateJobObject is asynchronous: never release a slot on its ACK alone."""
        deadline = time.monotonic() + timeout
        while True:
            if os.name == 'nt':
                class Accounting(ctypes.Structure):
                    _fields_ = [('times', ctypes.c_int64 * 4), ('faults', ctypes.c_uint32),
                                ('total', ctypes.c_uint32), ('active', ctypes.c_uint32),
                                ('terminated', ctypes.c_uint32)]
                value = Accounting()
                if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                if value.active == 0:
                    return
            elif self.pid:
                try:
                    os.killpg(self.pid, 0)
                except ProcessLookupError:
                    return
            else:
                return
            if time.monotonic() >= deadline:
                raise StopUnconfirmed('无法确认整个进程树已停止；保留执行槽')
            time.sleep(.02)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def spawn_contained(args, **kwargs):
    tree = ProcessTree(kwargs.pop('tree_name', None))
    proc = None
    try:
        if os.name == 'nt':
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x4  # CREATE_SUSPENDED
        else:
            kwargs['start_new_session'] = True
        proc = subprocess.Popen(args, **kwargs)
        tree.attach(proc.pid)
        if os.name == 'nt':
            ntdll = ctypes.WinDLL('ntdll')
            ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
            ntdll.NtResumeProcess.restype = ctypes.c_long
            if ntdll.NtResumeProcess(int(proc._handle)) != 0:
                raise RuntimeError('无法恢复受控脚本进程')
        proc._process_tree = tree
        return proc
    except BaseException:
        if proc:
            proc.kill()
            proc.wait()
        tree.close()
        raise


def stop_process_tree(proc):
    tree = getattr(proc, '_process_tree', None)
    if tree is None:
        raise RuntimeError('拒绝仅终止父进程：执行进程缺少进程树容器')
    try:
        tree.stop()
        proc.wait(timeout=10)
        tree.confirm_stopped()
        tree.close()
    except Exception as exc:
        raise StopUnconfirmed('进程树停止未确认') from exc
