"""单实例、只读已提交快照；提示不是交付保证，HTTP/CAS 始终为真源。"""
from threading import Lock

from sqlalchemy import case, or_

from app.auth import authenticate_access_token
from app.database import SessionLocal
from app.models import DeviceGrant, TaskExecution
from app.services.task_service import ACTIVE, device_auth


class ConnectionRegistry:
    def __init__(self, total_limit=128, device_limit=2):
        self.total_limit = total_limit
        self.device_limit = device_limit
        self._devices = {}
        self._lock = Lock()

    @property
    def count(self):
        with self._lock:
            return sum(self._devices.values())

    def acquire(self, device_id):
        with self._lock:
            count = self._devices.get(device_id, 0)
            if count >= self.device_limit or sum(self._devices.values()) >= self.total_limit:
                return False
            self._devices[device_id] = count + 1
            return True

    def release(self, device_id):
        with self._lock:
            count = self._devices.get(device_id, 0)
            if count <= 1:
                self._devices.pop(device_id, None)
            else:
                self._devices[device_id] = count - 1


registry = ConnectionRegistry()


def snapshot(device_id, token, device_token, session_factory=None):
    """仅在线程池调用；Session/ORM 不离开此函数，不提交也不调用 pending。"""
    with (session_factory or SessionLocal)() as db:
        user = authenticate_access_token(token, db)
        device = device_auth(db, device_id, user, device_token)
        executions = db.query(
            TaskExecution.id, TaskExecution.state, TaskExecution.attempt_id,
            TaskExecution.stopped,
        ).filter(
            TaskExecution.device_id == device_id,
            or_(TaskExecution.state.in_(ACTIVE), TaskExecution.id == device.active_execution_id),
        ).order_by(
            case((TaskExecution.id == device.active_execution_id, 0), else_=1),
            case((TaskExecution.state != "queued", 0), else_=1),
            TaskExecution.id,
        ).limit(101).all()
        grants = db.query(DeviceGrant.id, DeviceGrant.status).filter(
            DeviceGrant.device_id == device_id,
        ).order_by(DeviceGrant.id).limit(200).all()
        return (device.active_execution_id, tuple(tuple(row) for row in executions),
                tuple(tuple(row) for row in grants))
