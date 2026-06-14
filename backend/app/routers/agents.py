"""Agent client registration & heartbeat (design §4.4, §5.1 watchdog server-side).

Agent = remote machine identity + liveness from the server's perspective.
Coexists with Environment (local browser/python/venv config).
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Agent
from app.auth import get_current_user, require_role
from app.services.audit import write_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Server-side heartbeat timeout (design §5.1: >90s no heartbeat → offline)
HEARTBEAT_TIMEOUT_SEC = 90


class AgentRegister(BaseModel):
    machine_name: str
    machine_ip: Optional[str] = None
    agent_version: Optional[str] = None


class AgentHeartbeat(BaseModel):
    machine_ip: Optional[str] = None
    agent_version: Optional[str] = None


class AgentItem(BaseModel):
    id: int
    machine_name: str
    machine_ip: Optional[str] = None
    user_id: int
    status: str
    agent_version: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


def _get_or_create(db: Session, user_id: int, machine_name: str) -> Agent:
    """Upsert by (user_id, machine_name) — one agent record per user+machine."""
    return db.query(Agent).filter(
        Agent.user_id == user_id,
        Agent.machine_name == machine_name,
        Agent.is_deleted == False,
    ).first()


@router.post("/register", response_model=AgentItem)
def register_agent(
    req: AgentRegister,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Agent startup registration. Idempotent — same user+machine returns existing record."""
    if not req.machine_name or not req.machine_name.strip():
        raise HTTPException(status_code=400, detail="machine_name 为必填项")

    agent = _get_or_create(db, current_user.id, req.machine_name.strip())
    now = datetime.now(timezone.utc)
    if agent:
        agent.machine_ip = req.machine_ip
        agent.agent_version = req.agent_version
        agent.status = "online"
        agent.last_heartbeat = now
        agent.is_deleted = False
        db.commit()
        db.refresh(agent)
        return agent

    agent = Agent(
        machine_name=req.machine_name.strip(),
        machine_ip=req.machine_ip,
        user_id=current_user.id,
        status="online",
        agent_version=req.agent_version,
        last_heartbeat=now,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    write_audit(current_user.id, current_user.username, "agent.online",
                target_type="agent", target_id=agent.id,
                detail="{} ({})".format(req.machine_name, req.agent_version or "?"))
    return agent


@router.post("/{agent_id}/heartbeat")
def heartbeat(
    agent_id: int,
    req: AgentHeartbeat,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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

    agent.last_heartbeat = datetime.now(timezone.utc)
    agent.status = "online"
    if req.machine_ip is not None:
        agent.machine_ip = req.machine_ip
    if req.agent_version is not None:
        agent.agent_version = req.agent_version
    db.commit()
    return {"status": "ok", "agent_id": agent_id}


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
    agent.is_deleted = True
    agent.status = "offline"
    db.commit()
    write_audit(current_user.id, current_user.username, "agent.offline",
                target_type="agent", target_id=agent_id,
                detail="管理员删除")
    return {"message": "Agent 已移除"}
