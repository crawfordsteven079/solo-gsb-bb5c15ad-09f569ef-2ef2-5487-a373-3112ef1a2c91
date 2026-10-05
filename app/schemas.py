"""请求/响应 Pydantic 模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------- 判定 ----------

class InspectionItemIn(BaseModel):
    material_code: str = Field(..., description="物料类别代码，如 PET")
    contamination_kg: float = Field(..., description="该类别检验出的污染量(kg)")
    note: str = Field("", description="备注（可选）")


class DecisionCreate(BaseModel):
    batch_no: str = Field(..., min_length=1, description="批次编号")
    region: str = Field(..., min_length=1, description="来源区域")
    weight_kg: float = Field(..., description="来料总重量(kg)")
    items: list[InspectionItemIn] = Field(..., min_length=1, description="检验物料明细")
    rule_version: str | None = Field(None, description="指定规则版本；缺省用该区域当前生效版本")
    dry_run: bool = Field(False, description="true 时只试算不落库")


# ---------- 规则 ----------

class RuleSetCreate(BaseModel):
    version: str = Field(..., min_length=1)
    region: str = Field(..., min_length=1)
    content: dict[str, Any]
    note: str = ""
    activate: bool = Field(False, description="创建后是否立即在该区域生效")


class RuleSetOut(BaseModel):
    id: int
    version: str
    region: str
    content: dict[str, Any]
    note: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RegionActiveRule(BaseModel):
    region: str
    active_version: str | None
    rule_set_id: int | None


# ---------- 审计 ----------

class AuditOut(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_ref: str
    operator: str
    detail: dict[str, Any]
    created_at: datetime
