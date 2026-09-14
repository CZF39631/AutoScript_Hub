from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas import TaskCreate, TaskReport


@pytest.mark.parametrize('changes', [
    {'script_id': True}, {'script_version': '1'}, {'device_id': True},
    {'timeout_seconds': True}, {'requires_desktop': 'false'},
    {'requires_browser': 1}, {'params': {'number': float('nan')}},
    {'params': {'number': float('inf')}},
])
def test_task_payload_does_not_coerce_control_types_or_accept_nonfinite_json(changes):
    payload = dict(name='test', script_id=1, script_version=1, device_id=1, trigger={'kind': 'manual'})
    payload.update(changes)
    with pytest.raises(ValidationError):
        TaskCreate(**payload)


@pytest.mark.parametrize('stopped', [False, 0, 1, 'true', None])
def test_stop_report_requires_an_actual_true_boolean(stopped):
    with pytest.raises(ValidationError):
        TaskReport(attempt_id=uuid4(), state='success', stopped=stopped)
