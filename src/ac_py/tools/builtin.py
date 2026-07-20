"""构建 14 个售后业务工具，并把数据库查询封装为统一工具处理函数。"""

from collections.abc import Awaitable, Callable
from typing import Any

from ac_py.db.repositories import BusinessRepository
from ac_py.domain.enums import RiskLevel, Scene
from ac_py.domain.schemas import ToolSpec
from ac_py.tools.registry import RegisteredTool, ToolRegistry


def ticket_schema(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """生成以工单编号为必填项的 JSON Schema。"""

    properties: dict[str, Any] = {"ticket_id": {"type": "integer", "minimum": 1}}
    properties.update(extra or {})
    return {
        "type": "object",
        "properties": properties,
        "required": ["ticket_id"],
        "additionalProperties": False,
    }


def make_spec(
    name: str,
    description: str,
    scenes: set[Scene],
    *,
    risk: RiskLevel = RiskLevel.READ,
    schema: dict[str, Any] | None = None,
    permission: str = "ticket:read",
) -> ToolSpec:
    """构建统一工具定义，减少重复配置并保持约束一致。"""

    return ToolSpec(
        name=name,
        description=description,
        scenes=scenes,
        risk_level=risk,
        input_schema=schema or ticket_schema(),
        idempotent=risk != RiskLevel.HIGH,
        required_permission=permission,
    )


def wrap_ticket_query(
    query: Callable[[int], Awaitable[dict[str, Any] | list[dict[str, Any]]]],
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """把接收工单编号的仓储查询转换为标准工具处理函数。"""

    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        """执行仓储查询并用统一 data 节点包装结果。"""

        data = await query(int(arguments["ticket_id"]))
        return {"data": data}

    return handler


def create_business_registry(repository: BusinessRepository) -> ToolRegistry:
    """创建包含 14 个售后业务工具的默认注册表。"""

    registry = ToolRegistry()
    common = {Scene.OTHER}

    async def refund_timeline(arguments: dict[str, Any]) -> dict[str, Any]:
        """读取退款记录中的时间线。"""

        refund = await repository.get_refund(int(arguments["ticket_id"]))
        return {"data": refund.get("timeline", []), "status": refund.get("status")}

    async def create_refund(arguments: dict[str, Any]) -> dict[str, Any]:
        """在人工批准后写入退款申请处理记录。"""

        record = await repository.create_ticket_record(
            int(arguments["ticket_id"]),
            "agent",
            "refund_requested",
            str(arguments["reason"]),
        )
        return {"data": record}

    async def check_return(arguments: dict[str, Any]) -> dict[str, Any]:
        """根据订单和退货状态给出确定性的资格初筛。"""

        order = await repository.get_order_for_ticket(int(arguments["ticket_id"]))
        request = await repository.get_return_request(int(arguments["ticket_id"]))
        eligible = bool(order) and order.get("status") not in {"cancelled", "refunded"}
        return {"eligible": eligible, "order": order, "return_request": request}

    async def create_return(arguments: dict[str, Any]) -> dict[str, Any]:
        """在人工批准后写入退货申请处理记录。"""

        record = await repository.create_ticket_record(
            int(arguments["ticket_id"]),
            "agent",
            "return_requested",
            str(arguments["reason"]),
        )
        return {"data": record}

    async def check_logistics(arguments: dict[str, Any]) -> dict[str, Any]:
        """基于轨迹状态判断是否存在物流异常。"""

        logistics = await repository.get_logistics(int(arguments["ticket_id"]))
        abnormal = logistics.get("status") in {"stalled", "lost", "exception"}
        return {"abnormal": abnormal, "logistics": logistics}

    async def quality_evidence(arguments: dict[str, Any]) -> dict[str, Any]:
        """从工单历史中提取用户提交的质量证据记录。"""

        records = await repository.get_history(int(arguments["ticket_id"]))
        evidence = [item for item in records if item.get("action") == "quality_evidence"]
        return {"data": evidence}

    async def transfer(arguments: dict[str, Any]) -> dict[str, Any]:
        """创建转人工处理记录。"""

        record = await repository.create_ticket_record(
            int(arguments["ticket_id"]),
            "agent",
            "transfer_to_human",
            str(arguments.get("reason", "证据不足或状态冲突")),
        )
        return {"data": record}

    entries: list[tuple[ToolSpec, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]] = [
        (
            make_spec("get_ticket", "查询工单当前状态", common),
            wrap_ticket_query(repository.get_ticket),
        ),
        (
            make_spec("get_order", "查询工单关联订单", common),
            wrap_ticket_query(repository.get_order_for_ticket),
        ),
        (
            make_spec("get_ticket_history", "查询历史处理记录", common),
            wrap_ticket_query(repository.get_history),
        ),
        (
            make_spec("get_refund", "查询退款当前状态", {Scene.REFUND}),
            wrap_ticket_query(repository.get_refund),
        ),
        (
            make_spec("get_refund_timeline", "查询退款状态时间线", {Scene.REFUND}),
            refund_timeline,
        ),
        (
            make_spec(
                "create_refund_request",
                "创建需要人工审批的退款申请",
                {Scene.REFUND},
                risk=RiskLevel.HIGH,
                schema=ticket_schema({"reason": {"type": "string", "minLength": 1}}),
                permission="refund:write",
            ),
            create_refund,
        ),
        (
            make_spec("get_return_request", "查询退货申请", {Scene.RETURN}),
            wrap_ticket_query(repository.get_return_request),
        ),
        (
            make_spec("check_return_eligibility", "校验退货资格", {Scene.RETURN}),
            check_return,
        ),
        (
            make_spec(
                "create_return_request",
                "创建需要人工审批的退货申请",
                {Scene.RETURN},
                risk=RiskLevel.HIGH,
                schema=ticket_schema({"reason": {"type": "string", "minLength": 1}}),
                permission="return:write",
            ),
            create_return,
        ),
        (
            make_spec("get_logistics_track", "查询完整物流轨迹", {Scene.LOGISTICS}),
            wrap_ticket_query(repository.get_logistics),
        ),
        (
            make_spec("check_delivery_exception", "判断物流是否异常", {Scene.LOGISTICS}),
            check_logistics,
        ),
        (
            make_spec("get_product", "查询商品与分类", {Scene.QUALITY}),
            wrap_ticket_query(repository.get_product),
        ),
        (
            make_spec("get_quality_evidence", "读取商品质量证据", {Scene.QUALITY}),
            quality_evidence,
        ),
        (
            make_spec(
                "transfer_to_human",
                "将诊断转交人工处理",
                common,
                risk=RiskLevel.LOW,
                schema=ticket_schema({"reason": {"type": "string"}}),
                permission="ticket:transfer",
            ),
            transfer,
        ),
    ]
    for spec, handler in entries:
        registry.register(RegisteredTool(spec=spec, handler=handler))
    return registry
