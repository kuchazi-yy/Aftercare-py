"""实现业务事实、诊断轨迹和会话摘要的数据库查询与写入。"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_py.db.models import (
    DiagnosisResult,
    DiagnosisRun,
    DiagnosisSession,
    EvidenceCitation,
    IndexJob,
    Logistics,
    MemorySummary,
    Order,
    PolicyDocument,
    PolicySection,
    PolicyVersion,
    Product,
    Refund,
    ReturnRequest,
    Ticket,
    TicketRecord,
    ToolCallLog,
)
from ac_py.domain.enums import Scene
from ac_py.domain.schemas import BusinessContext, PolicyChunk, SearchHit, ToolResult


def model_dict(model: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    """把 SQLAlchemy 模型转换为不包含内部状态的普通字典。"""

    excluded = exclude or set()
    result: dict[str, Any] = {}
    for column in model.__table__.columns:
        if column.name in excluded:
            continue
        value = getattr(model, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return result


class BusinessRepository:
    """提供 MCP 业务工具所需的只读查询与受控写入。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """保存数据库会话工厂，确保每次工具调用独立管理事务。"""

        self._sessions = session_factory

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        """按工单编号查询工单，不存在时返回空字典。"""

        async with self._sessions() as session:
            ticket = await session.get(Ticket, ticket_id)
            return model_dict(ticket) if ticket else {}

    async def create_ticket(self, order_no: str, description: str) -> dict[str, Any]:
        """根据订单号创建售后工单并追加创建记录。"""

        async with self._sessions() as session:
            order = (await session.scalars(select(Order).where(Order.order_no == order_no))).first()
            if order is None:
                raise ValueError("订单不存在")
            ticket = Ticket(
                order_id=order.id,
                customer_id=order.customer_id,
                status="open",
                description=description,
            )
            session.add(ticket)
            await session.flush()
            session.add(
                TicketRecord(
                    ticket_id=ticket.id,
                    operator="customer",
                    action="create",
                    content=description,
                )
            )
            await session.commit()
            await session.refresh(ticket)
            return model_dict(ticket)

    async def update_ticket_status(
        self,
        ticket_id: int,
        status: str,
        content: str,
    ) -> dict[str, Any]:
        """更新工单状态并记录变更原因。"""

        async with self._sessions() as session:
            ticket = await session.get(Ticket, ticket_id)
            if ticket is None:
                raise ValueError("工单不存在")
            ticket.status = status
            session.add(
                TicketRecord(
                    ticket_id=ticket_id,
                    operator="agent",
                    action=f"status:{status}",
                    content=content,
                )
            )
            await session.commit()
            await session.refresh(ticket)
            return model_dict(ticket)

    async def get_order_for_ticket(self, ticket_id: int) -> dict[str, Any]:
        """通过工单查询关联订单。"""

        async with self._sessions() as session:
            statement = (
                select(Order)
                .join(Ticket, Ticket.order_id == Order.id)
                .where(Ticket.id == ticket_id)
            )
            order = (await session.scalars(statement)).first()
            return model_dict(order) if order else {}

    async def get_history(self, ticket_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """查询最近工单处理记录并按时间正序返回。"""

        async with self._sessions() as session:
            statement = (
                select(TicketRecord)
                .where(TicketRecord.ticket_id == ticket_id)
                .order_by(TicketRecord.id.desc())
                .limit(limit)
            )
            records = list((await session.scalars(statement)).all())
            return [model_dict(record) for record in reversed(records)]

    async def get_refund(self, ticket_id: int) -> dict[str, Any]:
        """查询工单关联订单的最新退款记录。"""

        async with self._sessions() as session:
            statement = (
                select(Refund)
                .join(Order, Refund.order_id == Order.id)
                .join(Ticket, Ticket.order_id == Order.id)
                .where(Ticket.id == ticket_id)
                .order_by(Refund.id.desc())
            )
            refund = (await session.scalars(statement)).first()
            return model_dict(refund) if refund else {}

    async def get_return_request(self, ticket_id: int) -> dict[str, Any]:
        """查询工单关联订单的最新退货申请。"""

        async with self._sessions() as session:
            statement = (
                select(ReturnRequest)
                .join(Order, ReturnRequest.order_id == Order.id)
                .join(Ticket, Ticket.order_id == Order.id)
                .where(Ticket.id == ticket_id)
                .order_by(ReturnRequest.id.desc())
            )
            request = (await session.scalars(statement)).first()
            return model_dict(request) if request else {}

    async def get_logistics(self, ticket_id: int) -> dict[str, Any]:
        """查询工单关联订单的物流轨迹。"""

        async with self._sessions() as session:
            statement = (
                select(Logistics)
                .join(Order, Logistics.order_id == Order.id)
                .join(Ticket, Ticket.order_id == Order.id)
                .where(Ticket.id == ticket_id)
            )
            logistics = (await session.scalars(statement)).first()
            return model_dict(logistics) if logistics else {}

    async def get_product(self, ticket_id: int) -> dict[str, Any]:
        """查询工单关联商品。"""

        async with self._sessions() as session:
            statement = (
                select(Product)
                .join(Order, Order.product_id == Product.id)
                .join(Ticket, Ticket.order_id == Order.id)
                .where(Ticket.id == ticket_id)
            )
            product = (await session.scalars(statement)).first()
            return model_dict(product) if product else {}

    async def create_ticket_record(
        self, ticket_id: int, operator: str, action: str, content: str
    ) -> dict[str, Any]:
        """为受控写工具追加工单处理记录并提交事务。"""

        async with self._sessions() as session:
            record = TicketRecord(
                ticket_id=ticket_id,
                operator=operator,
                action=action,
                content=content,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return model_dict(record)

    async def load_context(self, ticket_id: int) -> BusinessContext:
        """串行加载完整业务上下文，主要供管理接口和测试使用。"""

        return BusinessContext(
            ticket=await self.get_ticket(ticket_id),
            order=await self.get_order_for_ticket(ticket_id),
            history=await self.get_history(ticket_id),
            refund=await self.get_refund(ticket_id),
            return_request=await self.get_return_request(ticket_id),
            logistics=await self.get_logistics(ticket_id),
            product=await self.get_product(ticket_id),
        )


class DiagnosisRepository:
    """持久化诊断会话、执行记录、工具轨迹和最终结果。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """保存数据库会话工厂。"""

        self._sessions = session_factory

    async def start_run(self, session_id: str, run_id: str, ticket_id: int, scene: str) -> None:
        """创建或复用诊断会话并记录新的执行。"""

        async with self._sessions() as session:
            existing = await session.get(DiagnosisSession, session_id)
            if existing is None:
                session.add(DiagnosisSession(id=session_id, ticket_id=ticket_id, status="running"))
                await session.flush()
            session.add(
                DiagnosisRun(
                    id=run_id,
                    session_id=session_id,
                    status="running",
                    scene=scene,
                )
            )
            await session.commit()

    async def log_tool(self, run_id: str, result: ToolResult, request: dict[str, Any]) -> None:
        """保存工具请求、规范化结果和耗时。"""

        async with self._sessions() as session:
            session.add(
                ToolCallLog(
                    run_id=run_id,
                    tool_name=result.name,
                    request=request,
                    response=result.model_dump(mode="json"),
                    status="ok" if result.ok else "error",
                    latency_ms=result.latency_ms,
                )
            )
            await session.commit()

    async def complete_run(
        self,
        run_id: str,
        summary: str,
        answer: str,
        evidence_status: str,
        should_transfer: bool,
        first_progress_ms: int,
        first_token_ms: int | None,
        total_ms: int,
        evidence: list[SearchHit],
    ) -> None:
        """完成诊断执行并保存最终输出与性能数据。"""

        async with self._sessions() as session:
            run = await session.get(DiagnosisRun, run_id)
            if run is not None:
                run.status = "completed"
                run.first_progress_ms = first_progress_ms
                run.first_token_ms = first_token_ms
                run.total_ms = total_ms
            session.add(
                DiagnosisResult(
                    run_id=run_id,
                    summary=summary,
                    answer=answer,
                    evidence_status=evidence_status,
                    should_transfer=should_transfer,
                )
            )
            session.add_all(
                [
                    EvidenceCitation(
                        run_id=run_id,
                        chunk_id=hit.chunk.chunk_id,
                        rank=rank,
                        score=hit.rerank_score or hit.rrf_score,
                    )
                    for rank, hit in enumerate(evidence, start=1)
                ]
            )
            await session.commit()

    async def fail_run(self, run_id: str, error: str) -> None:
        """把异常终止的诊断执行标记为失败并保存精简错误。"""

        async with self._sessions() as session:
            run = await session.get(DiagnosisRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = error[:1000]
                await session.commit()

    async def latest_summary(self, ticket_id: int) -> str:
        """查询工单最近一次长期会话摘要。"""

        async with self._sessions() as session:
            statement = (
                select(MemorySummary)
                .where(MemorySummary.ticket_id == ticket_id)
                .order_by(MemorySummary.id.desc())
            )
            summary = (await session.scalars(statement)).first()
            return summary.summary if summary else ""


class KnowledgeRepository:
    """持久化政策版本、解析条款和索引任务状态。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """保存数据库会话工厂。"""

        self._sessions = session_factory

    async def create_version(
        self,
        title: str,
        source_uri: str,
        version: str,
        scene: Scene,
        content: str,
    ) -> tuple[int, int]:
        """创建政策文档、草稿版本和待执行索引任务。"""

        async with self._sessions() as session:
            document = PolicyDocument(title=title, source_uri=source_uri)
            session.add(document)
            await session.flush()
            policy_version = PolicyVersion(
                document_id=document.id,
                version=version,
                scene=scene.value,
                content=content,
                status="indexing",
            )
            session.add(policy_version)
            await session.flush()
            job = IndexJob(policy_version_id=policy_version.id, status="pending", detail={})
            session.add(job)
            await session.commit()
            return policy_version.id, job.id

    async def get_version(self, version_id: int) -> tuple[PolicyVersion, PolicyDocument] | None:
        """查询政策版本及其文档元数据。"""

        async with self._sessions() as session:
            statement = (
                select(PolicyVersion, PolicyDocument)
                .join(PolicyDocument, PolicyDocument.id == PolicyVersion.document_id)
                .where(PolicyVersion.id == version_id)
            )
            row = (await session.execute(statement)).first()
            return (row[0], row[1]) if row else None

    async def save_chunks(self, version_id: int, chunks: list[PolicyChunk]) -> None:
        """保存政策父章节与条款子块。"""

        async with self._sessions() as session:
            session.add_all(
                [
                    PolicySection(
                        policy_version_id=version_id,
                        chunk_id=chunk.chunk_id,
                        parent_chunk_id=chunk.parent_id,
                        level=chunk.level,
                        title=chunk.title,
                        content=chunk.content,
                    )
                    for chunk in chunks
                ]
            )
            await session.commit()

    async def finish_index_job(
        self,
        version_id: int,
        job_id: int,
        index_name: str,
    ) -> None:
        """把政策版本和索引任务标记为已发布。"""

        async with self._sessions() as session:
            policy_version = await session.get(PolicyVersion, version_id)
            job = await session.get(IndexJob, job_id)
            if policy_version is not None:
                policy_version.status = "active"
            if job is not None:
                job.status = "completed"
                job.detail = {"index_name": index_name}
            await session.commit()

    async def fail_index_job(self, job_id: int, error: str) -> None:
        """记录索引任务失败原因。"""

        async with self._sessions() as session:
            job = await session.get(IndexJob, job_id)
            if job is not None:
                job.status = "failed"
                job.detail = {"error": error[:1000]}
            await session.commit()
