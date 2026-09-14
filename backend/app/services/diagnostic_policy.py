"""管理员控制的全局诊断策略；客户端请求不能覆盖。"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.models import ServerSettings
from shared.diagnostics import redact_data, redact_text, sensitive_values


class DiagnosticPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool = True
    redact_logs: bool = True
    redact_params: bool = True
    redact_summary: bool = True
    custom_sensitive_fields: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("custom_sensitive_fields")
    @classmethod
    def validate_fields(cls, fields):
        result = []
        for field in fields:
            field = field.strip()
            if not field or len(field) > 64 or any(ord(char) < 32 or ord(char) == 127 for char in field):
                raise ValueError("敏感字段必须是 1–64 字符的名称，不能包含控制字符")
            if field.casefold() not in {item.casefold() for item in result}:
                result.append(field)
        return result

    def protects(self, section):
        return self.enabled and getattr(self, "redact_" + section)

    def secrets(self, params):
        return sensitive_values(params, self.custom_sensitive_fields)

    def text(self, value, section, secrets=()):
        if value is None or not self.protects(section):
            return value
        return redact_text(value, secrets, self.custom_sensitive_fields)

    def params(self, value, secrets=()):
        return redact_data(value, secrets, self.custom_sensitive_fields) if self.protects("params") else value

    def weakens(self, previous):
        return any(previous.protects(section) and not self.protects(section)
                   for section in ("logs", "params", "summary")) or (
            previous.enabled and bool(set(previous.custom_sensitive_fields) - set(self.custom_sensitive_fields))
        )


def load_diagnostic_policy(db):
    row = db.query(ServerSettings).filter(ServerSettings.id == 1).first()
    if row is None:
        return DiagnosticPolicy()
    try:
        return DiagnosticPolicy.model_validate_json(row.diagnostic_policy_json)
    except (ValidationError, TypeError):
        # 无效存储不得意外关闭保护；不把配置内容写进日志。
        return DiagnosticPolicy()
