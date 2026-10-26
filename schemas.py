"""Validated agent outputs, separate from LangGraph's transient state."""
from typing import Literal

from pydantic import BaseModel, Field

SECTIONS = ["目标与用户", "范围与边界", "流程与确认", "数据与依赖", "权限与异常", "验收标准", "排期与约束"]


class AgentError(Exception):
    """User-safe model/workflow error; never includes credentials or raw responses."""


class Requirement(BaseModel):
    section: Literal["目标与用户", "范围与边界", "流程与确认", "数据与依赖", "权限与异常", "验收标准", "排期与约束"]
    text: str = Field(min_length=1, max_length=2000)
    status: Literal["已确认", "待确认", "存在冲突"]
    sources: list[str] = Field(default_factory=list, max_length=30)


class Summary(BaseModel):
    overview: str = Field(min_length=1, max_length=2000)
    requirements: list[Requirement] = Field(min_length=1, max_length=80)
    questions: list[str] = Field(default_factory=list, max_length=20)
