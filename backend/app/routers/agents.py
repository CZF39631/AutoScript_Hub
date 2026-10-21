"""Agent client registration & heartbeat (design §4.4, §5.1 watchdog server-side).

Agent = remote machine identity + liveness from the server's perspective.
Coexists with Environment (local browser/python/venv config).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Agent, Run
from app.schemas import RunBrief
from app.auth import create_agent_token, get_current_user, require_role, verify_agent_token
from app.services.agent_thumbnails import delete_thumbnail, read_bounded_jpeg, replace_thumbnail
from app.services.audit import write_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Server-side heartbeat timeout (design §5.1: >90s no heartbeat → offline)
HEARTBEAT_TIMEOUT_SEC = 90


class AgentRegister(BaseModel):
    device_uid: Optional[str] = Field(default=None, min_length=1, max_length=255)
    machine_name: str = Field(min_length=1, max_length=200)
    machine_ip: Optional[str] = None
    agent_version: Optional[str] = None
    mode: Optional[Literal["standard", "managed"]] = None
    enabled: Optional[bool] = None


class AgentHeartbeat(BaseModel):
    machine_ip: Optional[str] = None
    agent_version: Optional[str] = None


class AgentItem(BaseModel):
    id: int
    device_uid: str
    machine_name: str
    machine_ip: Optional[str] = None
    user_id: int
    mode: str
    enabled: bool
    status: str
    agent_version: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentRegisterResponse(AgentItem):
    agent_token: str


def _legacy_device_uid(user_id: int, machine_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "autoscript-hub:{}:{}".format(user_id, machine_name)))


def _find_registered_agent(
    db: Session, user_id: int, machine_name: str, device_uid: Optional[str]
) -> Optional[Agent]:
    """Prefer stable identity and only name-match records known to be legacy."""
    if device_uid:
        agent = db.query(Agent).filter(Agent.device_uid == device_uid).first()
        if agent:
            if agent.user_id != user_id:
                raise HTTPException(status_code=409, detail="device_uid 已绑定其他用户")
            if agent.is_deleted:
                raise HTTPException(status_code=403, detail="Agent 已被管理员移除")
            return agent

        legacy_uids = (
            "legacy-",
            _legacy_device_uid(user_id, machine_name),
        )
        candidates = db.query(Agent).filter(
            Agent.user_id == user_id,
            Agent.machine_name == machine_name,
            Agent.is_deleted == False,
        ).all()
        for candidate in candidates:
            if candidate.device_uid.startswith(legacy_uids[0]) or candidate.device_uid == legacy_uids[1]:
                return candidate
        return None

    return db.query(Agent).filter(
        Agent.user_id == user_id,
        Agent.machine_name == machine_name,
        Agent.is_deleted == False,
    ).first()


@router.post("/register", response_model=AgentRegisterResponse)
def register_agent(
    req: AgentRegister,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
):
    """Agent startup registration. Idempotent — same user+machine returns existing record."""
    if not req.machine_name or not req.machine_name.strip():
        raise HTTPException(status_code=400, detail="machine_name 为必填项")

    machine_name = req.machine_name.strip()
    device_uid = req.device_uid.strip() if req.device_uid else None
    agent = _find_registered_agent(db, current_user.id, machine_name, device_uid)
    now = datetime.now(timezone.utc)
    if agent:
        becomes_managed = agent.mode == "managed" or req.mode == "managed"
        if becomes_managed and agent.agent_token_issued_at is not None:
            verify_agent_token(agent_token, agent, allow_expired=True)
        elif becomes_managed and agent.machine_name != machine_name:
            # The single legacy bootstrap is deliberately tied to the old machine
            # record. Once issued, every subsequent registration needs the token.
            raise HTTPException(status_code=403, detail="旧版托管 Agent 设备信息不匹配")
        if device_uid and agent.device_uid != device_uid:
            agent.device_uid = device_uid
        agent.machine_name = machine_name
        agent.machine_ip = req.machine_ip
        agent.agent_version = req.agent_version
        if req.mode is not None:
            agent.mode = req.mode
        agent.status = "online" if agent.enabled else "offline"
        agent.last_heartbeat = now
        agent.agent_token_issued_at = agent.agent_token_issued_at or now
        db.commit()
        db.refresh(agent)
        return AgentRegisterResponse(
            **AgentItem.model_validate(agent).model_dump(),
            agent_token=create_agent_token(agent.id, agent.user_id),
        )

    agent = Agent(
        device_uid=device_uid or _legacy_device_uid(current_user.id, machine_name),
        machine_name=machine_name,
        machine_ip=req.machine_ip,
        user_id=current_user.id,
        mode=req.mode or "standard",
        enabled=True if req.enabled is None else req.enabled,
        status="online" if req.enabled is not False else "offline",
        agent_version=req.agent_version,
        last_heartbeat=now,
        agent_token_issued_at=now,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    write_audit(current_user.id, current_user.username, "agent.online",
                target_type="agent", target_id=agent.id,
                detail="{} ({})".format(req.machine_name, req.agent_version or "?"))
    return AgentRegisterResponse(
        **AgentItem.model_validate(agent).model_dump(),
        agent_token=create_agent_token(agent.id, agent.user_id),
    )


@router.post("/{agent_id}/heartbeat")
def heartbeat(
    agent_id: int,
    req: AgentHeartbeat,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
):
    """Agent heartbeat. Updates last_heartbeat and marks online.

    Called by client after every poll cycle. Server-side timeout scanner
    (see app.tasks.heartbeat_scanner) marks stale agents offline.
    """
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.user_id == current_user.id,
        Agent.is_deleted == False,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 未注册")
    if not agent.enabled:
        raise HTTPException(status_code=403, detail="Agent 已禁用")
    verify_agent_token(agent_token, agent)

    agent.last_heartbeat = datetime.now(timezone.utc)
    agent.status = "online"
    if req.machine_ip is not None:
        agent.machine_ip = req.machine_ip
    if req.agent_version is not None:
        agent.agent_version = req.agent_version
    db.commit()
    return {"status": "ok", "agent_id": agent_id}


@router.post("/{agent_id}/thumbnail")
async def upload_thumbnail(
    agent_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
):
    """Replace this managed device's thumbnail using both user and device credentials."""
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.user_id == current_user.id,
        Agent.mode == "managed",
        Agent.enabled == True,
        Agent.is_deleted == False,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="托管 Agent 不存在或已禁用")
    verify_agent_token(agent_token, agent)

    data, width, height = await read_bounded_jpeg(request)
    replace_thumbnail(agent.id, data)
    agent.thumbnail_updated_at = datetime.now(timezone.utc)
    agent.thumbnail_size = len(data)
    db.commit()
    db.refresh(agent)
    return {
        "agent_id": agent.id,
        "thumbnail_updated_at": agent.thumbnail_updated_at,
        "thumbnail_size": agent.thumbnail_size,
        "width": width,
        "height": height,
    }


@router.get("", response_model=List[AgentItem])
def list_agents(
    current_user: User = Depends(require_role("admin", "developer")),
    db: Session = Depends(get_db),
):
    """List all registered agents. Admin/developer only (design §1.3)."""
    return db.query(Agent).filter(
        Agent.is_deleted == False
    ).order_by(Agent.status.desc(), Agent.last_heartbeat.desc()).all()


@router.get("/mine", response_model=List[AgentItem])
def list_my_agents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List current user's own agents (for operators)."""
    return db.query(Agent).filter(
        Agent.user_id == current_user.id,
        Agent.is_deleted == False,
    ).order_by(Agent.last_heartbeat.desc()).all()


@router.get("/{agent_id}/next", response_model=Optional[RunBrief], responses={204: {"description": "暂无任务"}})
def get_next_run(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent_token: Optional[str] = Header(default=None, alias="X-Agent-Token"),
):
    """Return only work eligible for this exact device; claiming remains atomic."""
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.user_id == current_user.id,
        Agent.enabled == True,
        Agent.is_deleted == False,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在或已禁用")
    verify_agent_token(agent_token, agent)

    now = datetime.now(timezone.utc)
    query = db.query(Run).filter(
        Run.user_id == current_user.id,
        Run.status == "pending",
        Run.is_deleted == False,
        or_(Run.scheduled_for.is_(None), Run.scheduled_for <= now),
        or_(Run.expires_at.is_(None), Run.expires_at > now),
    )
    if agent.mode == "managed":
        query = query.filter(Run.target_agent_id == agent.id)
    else:
        query = query.filter(Run.target_agent_id.is_(None))
    run = query.order_by(Run.scheduled_for.asc(), Run.created_at.asc()).first()
    if run is None:
        return Response(status_code=204)
    from app.routers.runs import _enrich_run
    return _enrich_run(run, db)


@router.get("/{agent_id}", response_model=AgentItem)
def get_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    agent = db.query(Agent).filter(
        Agent.id == agent_id, Agent.is_deleted == False
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    # Operators can only see their own
    if current_user.role == "operator" and agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限访问")
    return agent


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Soft-delete an agent record. Admin only."""
    agent = db.query(Agent).filter(
        Agent.id == agent_id, Agent.is_deleted == False
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    # Refuse to report a successful device deletion if its retained screen data
    # could not also be removed.
    delete_thumbnail(agent.id)
    agent.thumbnail_updated_at = None
    agent.thumbnail_size = None
    agent.is_deleted = True
    agent.status = "offline"
    db.commit()
    write_audit(current_user.id, current_user.username, "agent.offline",
                target_type="agent", target_id=agent_id,
                detail="管理员删除")
    return {"message": "Agent 已移除"}
