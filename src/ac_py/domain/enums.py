"""定义售后诊断使用的场景、风险、任务和证据状态枚举。"""

from enum import StrEnum


class Scene(StrEnum):
    """表示一次售后问题所属的业务场景。"""

    REFUND = "refund"
    RETURN = "return"
    LOGISTICS = "logistics"
    QUALITY = "quality"
    OTHER = "other"


class RiskLevel(StrEnum):
    """表示工具执行或诊断结论的风险等级。"""

    READ = "read"
    LOW = "low"
    HIGH = "high"


class EvidenceStatus(StrEnum):
    """表示业务事实与政策证据的完整性状态。"""

    OK = "ok"
    INSUFFICIENT = "insufficient"
    CONFLICT = "conflict"


class RunStatus(StrEnum):
    """表示诊断工作流的生命周期状态。"""

    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalDecision(StrEnum):
    """表示人工对高风险动作作出的处理决定。"""

    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
