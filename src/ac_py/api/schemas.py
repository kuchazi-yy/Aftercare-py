"""定义对外 HTTP 接口使用的请求模型。"""

from typing import Any

from pydantic import BaseModel, Field

from ac_py.domain.enums import ApprovalDecision, Scene


class CreateTicketRequest(BaseModel):
    """表示创建工单请求。"""

    order_no: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=4000)


class UpdateTicketStatusRequest(BaseModel):
    """表示工单状态更新请求。"""

    status: str = Field(min_length=1, max_length=32)
    content: str = Field(default="", max_length=2000)


class DiagnoseRequest(BaseModel):
    """表示启动一次诊断的输入。"""

    ticket_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class ResumeRequest(BaseModel):
    """表示人工恢复中断任务的决定。"""

    decision: ApprovalDecision
    note: str = Field(default="", max_length=1000)
    edited_payload: dict[str, Any] | None = None


class PolicyIndexRequest(BaseModel):
    """表示纯文本政策索引请求。"""

    title: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=64)
    scene: Scene
    content: str = Field(min_length=1)


class SearchDebugRequest(BaseModel):
    """表示检索调试请求。"""

    query: str = Field(min_length=1, max_length=2000)
    scene: Scene
