import json
import os
import io
import time
import asyncio
import logging
import zipfile
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Script, Run
from app.schemas import ExecuteRequest, RunBrief, RunDetail
from app.auth import get_current_user, require_role
from app.config import LOGS_DIR, PROJECT_ROOT
from app.services.audit import write_audit

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _ensure_aware(dt):
    """SQLite strips tzinfo on round-trip; reattach UTC before arithmetic with aware datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_log_file(run, run_id):
    """Locate the log file for a run.

    Agent writes logs to its own _LOGS_DIR (which may differ from the server's LOGS_DIR,
    especially in dev where client_config.json's script_download_dir is empty → Agent uses
    PROJECT_ROOT/logs/). Try multiple candidate locations so the UI can always find the log:
      1. run.log_path (authority — Agent reports where it actually wrote), resolved vs PROJECT_ROOT
      2. {LOGS_DIR}/{run_id}.log  (server-side default)
      3. {PROJECT_ROOT}/logs/{run_id}.log  (Agent's default when its _LOGS_DIR is relative)
    Returns the first existing path, or None.
    """
    candidates = []
    if run and run.log_path:
        rp = run.log_path
        candidates.append(rp if os.path.isabs(rp) else os.path.join(PROJECT_ROOT, rp))
    candidates.append(os.path.join(LOGS_DIR, "{}.log".format(run_id)))
    candidates.append(os.path.join(PROJECT_ROOT, "logs", "{}.log".format(run_id)))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _validate_params(param_defs, params):
    """Validate user-submitted params against config definitions. Returns list of error strings.

    NOTE (design §5.2): file/folder existence is NOT checked here — those files live on the
    client machine and the backend cannot verify them. Existence checks are performed by the
    Agent before invoking main(). Only format-level checks (required, number range, select
    options) run on the backend.
    """
    errors = []
    param_map = {p["key"]: p for p in param_defs}

    for key, defn in param_map.items():
        val = params.get(key)
        ptype = defn.get("type", "text")
        label = defn.get("label", key)

        if defn.get("required") and (val is None or val == ""):
            errors.append("{}: {}".format(label, "不能为空"))
            continue

        if val is None or val == "":
            continue

        if ptype == "number":
            try:
                num = float(val)
            except (TypeError, ValueError):
                errors.append("{}: 不是有效数字".format(label))
                continue
            if defn.get("min") is not None and num < defn["min"]:
                errors.append("{}: 值不能小于{}".format(label, defn["min"]))
            if defn.get("max") is not None and num > defn["max"]:
                errors.append("{}: 值不能大于{}".format(label, defn["max"]))
        elif ptype == "select":
            opts = defn.get("options", [])
            if opts and val not in opts:
                errors.append("{}: 无效选项".format(label))

    return errors


class RunStatusUpdate(BaseModel):
    status: str  # running / success / failed / cancelled
    error_msg: Optional[str] = None
    result_files: Optional[str] = None
    log_path: Optional[str] = None


@router.post("/execute", response_model=RunBrief)
def execute_script(
    req: ExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    script = db.query(Script).filter(
        Script.id == req.script_id,
        Script.is_deleted == False,
        Script.status == "active",
    ).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在或未启用")

    # Check for active runs — auto-cancel stale pending runs (>5 min)
    active = db.query(Run).filter(
        Run.user_id == current_user.id,
        Run.status.in_(["pending", "running"]),
        Run.is_deleted == False,
    ).first()
    if active:
        if active.status == "pending":
            stale_secs = (datetime.now(timezone.utc) - _ensure_aware(active.created_at)).total_seconds()
            if stale_secs > 300:  # 5 minutes
                active.status = "cancelled"
                active.finished_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(active)
            else:
                raise HTTPException(status_code=409, detail="当前有任务正在执行,请等待完成")
        else:
            raise HTTPException(status_code=409, detail="当前有任务正在执行,请等待完成")

    # Validate params against config
    if script.config_json:
        config = json.loads(script.config_json)
        param_defs = config.get("params", [])
        errors = _validate_params(param_defs, req.params)
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(errors))

    run = Run(
        script_id=script.id,
        script_version=script.latest_version,
        user_id=current_user.id,
        status="pending",
        params=json.dumps(req.params, ensure_ascii=False),
        environment_id=req.environment_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    write_audit(current_user.id, current_user.username, "execute_script",
                target_type="run", target_id=run.id,
                detail="script={} v{}".format(script.name, script.latest_version))
    return run


@router.get("", response_model=List[RunBrief])
def list_runs(
    script_id: Optional[int] = None,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Run).filter(Run.is_deleted == False)
    if current_user.role == "operator":
        q = q.filter(Run.user_id == current_user.id)
    if script_id:
        q = q.filter(Run.script_id == script_id)
    if status:
        q = q.filter(Run.status == status)
    if user_id:
        q = q.filter(Run.user_id == user_id)
    if date_from:
        from datetime import datetime as dt
        try:
            q = q.filter(Run.created_at >= dt.fromisoformat(date_from))
        except ValueError:
            pass  # invalid date format, skip filter
    if date_to:
        from datetime import datetime as dt
        try:
            q = q.filter(Run.created_at < dt.fromisoformat(date_to))
        except ValueError:
            pass  # invalid date format, skip filter

    runs = q.order_by(Run.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for r in runs:
        item = RunBrief.from_orm(r)
        user = db.query(User).filter(User.id == r.user_id).first()
        item.username = user.display_name if user else None
        script = db.query(Script).filter(Script.id == r.script_id).first()
        item.script_name = script.name if script else None
        result.append(item)
    return result


@router.get("/filter-options/users")
def filter_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == "operator":
        return [{"id": current_user.id, "name": current_user.display_name}]
    users = db.query(User).filter(User.is_deleted == False).all()
    return [{"id": u.id, "name": u.display_name} for u in users]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if current_user.role == "operator" and run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问")
    return run


@router.patch("/{run_id}/status")
def update_run_status(
    run_id: int,
    update: RunStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if run.user_id != current_user.id and current_user.role == "operator":
        raise HTTPException(status_code=403, detail="无权限访问")

    run.status = update.status
    if update.status == "running":
        run.started_at = datetime.now(timezone.utc)
    if update.status in ("success", "failed", "cancelled"):
        run.finished_at = datetime.now(timezone.utc)
        if run.started_at:
            run.duration_sec = int((run.finished_at - _ensure_aware(run.started_at)).total_seconds())
    if update.error_msg:
        run.error_msg = update.error_msg
    if update.result_files:
        run.result_files = update.result_files
    if update.log_path:
        run.log_path = update.log_path
    db.commit()
    return {"message": "状态已更新"}


@router.post("/{run_id}/cancel")
def cancel_run(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="该任务无法取消")
    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    if run.started_at:
        run.duration_sec = int((run.finished_at - _ensure_aware(run.started_at)).total_seconds())
    db.commit()
    write_audit(current_user.id, current_user.username, "cancel_run",
                target_type="run", target_id=run_id)
    return {"message": "任务已取消"}


@router.get("/{run_id}/log")
def get_run_log(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if current_user.role == "operator" and run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问")

    log_file = _resolve_log_file(run, run_id)
    if not log_file:
        return {"log": ""}
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        return {"log": f.read()}


@router.get("/{run_id}/log/stream")
def stream_run_log(
    run_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    from jose import JWTError, jwt
    from app.config import JWT_SECRET, JWT_ALGORITHM
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="无效的令牌")
    current_user = db.query(User).filter(
        User.id == user_id, User.status == "active", User.is_deleted == False
    ).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="用户不存在")

    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if current_user.role == "operator" and run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问")

    log_file = _resolve_log_file(run, run_id)
    if not log_file:
        # Log not generated yet (run just started) — watch the Agent's default location
        # so the SSE generator can stream content as soon as the file appears.
        log_file = os.path.join(PROJECT_ROOT, "logs", "{}.log".format(run_id))

    def event_generator():
        from app.database import SessionLocal
        pos = 0
        idle_count = 0
        while True:
            db2 = SessionLocal()
            try:
                r = db2.query(Run).filter(Run.id == run_id).first()
                alive = r and r.status in ("pending", "running")
            finally:
                db2.close()

            if os.path.isfile(log_file):
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                if chunk:
                    idle_count = 0
                    yield "data: {}\n\n".format(json.dumps({"log": chunk}, ensure_ascii=False))
                else:
                    idle_count += 1
            else:
                idle_count += 1

            if not alive:
                yield "data: {\"done\": true}\n\n"
                break
            # Timeout: no new data for 600s while alive
            if idle_count > 600:
                yield "data: {\"done\": true}\n\n"
                break

            time.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/open-result")
def open_result_file(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if current_user.role == "operator" and run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问")
    if not run.result_files:
        raise HTTPException(status_code=400, detail="无结果文件")

    file_path = json.loads(run.result_files)
    if isinstance(file_path, list):
        file_path = file_path[0]
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在: {}".format(file_path))

    os.startfile(file_path)
    return {"message": "已打开"}


@router.get("/{run_id}/download")
def download_result(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download run result file(s). Single file → direct download; multiple → zipped."""
    run = db.query(Run).filter(Run.id == run_id, Run.is_deleted == False).first()
    if not run:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if current_user.role == "operator" and run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问")
    if not run.result_files:
        raise HTTPException(status_code=400, detail="无结果文件")

    paths = json.loads(run.result_files)
    if isinstance(paths, str):
        paths = [paths]

    existing = [p for p in paths if isinstance(p, str) and os.path.isfile(p)]
    if not existing:
        raise HTTPException(status_code=404, detail="结果文件在服务器上不存在")

    if len(existing) == 1:
        f = existing[0]
        return FileResponse(f, filename=os.path.basename(f))

    # Multiple files: stream a zip
    def _zip_iter():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in existing:
                zf.write(fp, os.path.basename(fp))
        buf.seek(0)
        yield buf.read()

    return StreamingResponse(
        _zip_iter(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=run_{}_results.zip".format(run_id)},
    )
