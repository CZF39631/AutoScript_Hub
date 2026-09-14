"""One lifetime Agent gate plus cancellable, contained environment preparation."""
import multiprocessing
import os
import time
from pathlib import Path

from client.runtime.process_tree import ProcessTree, StopUnconfirmed, stop_process_tree, containment_name


class ExecutionGate:
    """OS releases the lock on Agent death; never steal a lock by wall-clock age."""
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, 'a+b')
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('另一个 Agent 已占用本机执行门禁')

    def close(self):
        if not self.file.closed:
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()


def _prepare_child(pipe, ready, release, config, paths, index_url, offline):
    if os.name != 'nt':
        os.setsid()
    ready.set()
    release.wait()  # Parent must attach containment before any dependency installer.
    try:
        import sys
        from client.runtime.python_runtime import private_python, PrivatePythonUnavailable
        from client.runtime.environment_manager import ensure_environment
        try:
            runtime = private_python(paths)
        except PrivatePythonUnavailable:
            if getattr(sys, 'frozen', False):
                raise
            runtime = Path(sys.executable)
        result = ensure_environment(config.get('requirements', []), paths,
                                    index_url=index_url, offline=offline, python_executable=runtime)
        pipe.send((str(result.python_executable), None))
    except BaseException as exc:
        pipe.send((None, '环境准备失败: ' + str(exc)))
    finally:
        pipe.close()


def prepare_environment(config, paths, index_url, offline, cancelled, timeout=300):
    ctx = multiprocessing.get_context('spawn')
    parent, child = ctx.Pipe(duplex=False)
    ready, release = ctx.Event(), ctx.Event()
    tree = ProcessTree(containment_name(paths, 'prepare'))
    proc = ctx.Process(target=_prepare_child, args=(child, ready, release, config, paths, index_url, offline))
    started = time.monotonic()
    try:
        proc.start()
        child.close()
        if os.name == 'nt':
            tree.attach(proc.pid)
        while not ready.wait(.05):
            if cancelled.is_set() or time.monotonic() - started > timeout or not proc.is_alive():
                raise RuntimeError('准备已取消、超时或子进程退出')
        if os.name != 'nt':
            tree.attach(proc.pid)
        release.set()
        while not parent.poll(.05):
            if cancelled.is_set():
                raise RuntimeError('准备已取消')
            if time.monotonic() - started > timeout:
                raise RuntimeError('环境准备超过 {} 秒'.format(timeout))
            if not proc.is_alive():
                raise RuntimeError('环境准备进程意外退出')
        executable, error = parent.recv()
        if error:
            raise RuntimeError(error)
        return executable
    finally:
        if proc.pid:
            try:
                tree.stop()
                if proc.is_alive():
                    proc.terminate()
                proc.join(10)
                if proc.is_alive():
                    raise StopUnconfirmed('无法确认环境准备进程已停止')
                tree.confirm_stopped()
            except Exception as exc:
                raise StopUnconfirmed('环境准备进程树停止未确认') from exc
        tree.close()
        parent.close()
        child.close()


def check_conditions(body, browser_detector):
    if body.get('requires_desktop'):
        if os.name != 'nt':
            raise ValueError('无法验证交互桌面；任务不会唤醒休眠机')
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user.OpenInputDesktop.restype = wintypes.HANDLE
        user.SwitchDesktop.argtypes = [wintypes.HANDLE]
        user.CloseDesktop.argtypes = [wintypes.HANDLE]
        desktop = user.OpenInputDesktop(0, False, 0x0100)
        if not desktop:
            raise ValueError('交互桌面不可用；任务不会解锁或唤醒休眠机')
        try:
            if not user.SwitchDesktop(desktop):
                raise ValueError('交互桌面已锁定或不可用')
        finally:
            user.CloseDesktop(desktop)
    if body.get('requires_browser') and not browser_detector():
        raise ValueError('本机没有检测到可用浏览器')


class ExecutionController:
    """All sources share a reserved slot, including preparation and stop verification.

    Callbacks perform application-specific cache/auth/report work. A failed report
    never implies a second execution; the durable ledger is the source of truth.
    """
    def __init__(self, store, prepare, spawn, complete, start_ack=None):
        import threading
        self.store, self.prepare, self.spawn, self.complete = store, prepare, spawn, complete
        self.start_ack = start_ack
        self.lock = threading.RLock()
        self.active = None
        self.worker = None

    def submit(self, ident, body, source='local'):
        import threading
        with self.lock:
            if self.active is not None:
                return {'error': 'another task is running'}
            timeout = body.get('timeout_seconds', 600)
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
                raise ValueError('timeout_seconds 必须为 1–86400 的整数')
            self.store.intent(str(ident), body)  # FULL synchronous commit BEFORE prepare/spawn.
            started = time.monotonic()
            self.active = {'id': str(ident), 'body': dict(body), 'source': source,
                           'cancel': threading.Event(), 'started_monotonic': started, 'deadline': started + timeout,
                           'state': 'preparing'}
            self.worker = threading.Thread(target=self._run, args=(self.active,), daemon=True,
                                           name='controlled-execution')
            self.worker.start()
            return {'id': str(ident), 'status': 'preparing'}

    def cancel(self, ident):
        with self.lock:
            if self.active is None or str(ident) not in (
                    self.active['id'], str(self.active['body'].get('run_id', ''))):
                raise ValueError('本机没有对应的活动执行')
            self.active['cancel'].set()
            return {'id': str(ident), 'status': 'cancel_requested'}

    def _guard(self, item):
        if item['cancel'].is_set():
            raise InterruptedError('执行已取消')
        if time.monotonic() >= item['deadline']:
            raise TimeoutError('执行超时（含环境准备）')

    def _run(self, item):
        proc = None
        state, error, stopped = 'failed', None, True
        try:
            self._guard(item)
            prepared = self.prepare(item)
            self._guard(item)
            if self.start_ack is not None and item['source'] == 'remote':
                # A lost ACK is unknowable, never repeat start or execute on recovery.
                self.store.attempt_state(item['body']['execution_id'], 'start_intent')
                state = 'unknown'
                if not self.start_ack(item):
                    raise RuntimeError('启动未获唯一确认；禁止重试执行')
                state = 'failed'
            self._guard(item)
            self.store.state(item['id'], 'running')
            proc = self.spawn(item, prepared)
            stopped = False
            item['state'] = 'running'
            while proc.poll() is None:
                self._guard(item)
                item['cancel'].wait(.05)
            state = 'success' if proc.returncode == 0 else 'failed'
            if state == 'failed':
                error = 'Exit code: {}'.format(proc.returncode)
        except StopUnconfirmed as exc:
            stopped, state, error = False, 'unknown', str(exc)
        except InterruptedError as exc:
            state, error = 'cancelled', str(exc)
        except Exception as exc:
            error = str(exc)
        finally:
            if proc is not None:
                try:
                    stop_process_tree(proc)  # Also terminate descendants after parent exits.
                    stopped = True
                    proc._log_file.close()
                    os.remove(proc._params_file)
                except (OSError, AttributeError) as exc:
                    if not stopped:
                        state, error = 'unknown', str(exc)
                except Exception as exc:
                    stopped, state, error = False, 'unknown', str(exc)
            item.update(state=state, stopped=stopped, error_msg=error)
            try:
                self.store.state(item['id'], state, error)
                if stopped:
                    self.complete(item)
                    with self.lock:
                        self.active = None
            except Exception as exc:
                # Retain the slot until the terminal fact is durably recorded.
                item['persistence_error'] = type(exc).__name__
            # Unconfirmed stop intentionally latches the slot; restart reconciliation
            # requires the lifetime lock and kill-on-close containment, not wall time.
