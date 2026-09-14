"""独立工单诊断快照；过期记录保留墓碑，不回退原执行数据。"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.models import Base


class IssueDiagnostic(Base):
    __tablename__ = "issue_diagnostics"
    issue_id = Column(Integer, ForeignKey("issues.id"), primary_key=True)
    state = Column(String(32), nullable=False, default="collected")
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
