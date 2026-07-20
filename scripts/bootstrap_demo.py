"""创建最小演示业务数据，并将本地售后政策发布到 Elasticsearch。"""

import argparse
import asyncio
from pathlib import Path

from elasticsearch import AsyncElasticsearch
from sqlalchemy import select

from ac_py.config import get_settings
from ac_py.db.base import Database
from ac_py.db.models import Customer, Logistics, Order, Product, Refund, Ticket, TicketRecord
from ac_py.domain.enums import Scene
from ac_py.llm.client import OpenAICompatibleClient
from ac_py.rag.chunking import split_policy
from ac_py.rag.indexer import PolicyIndexer

POLICY_SCENES = {
    "refund.md": Scene.REFUND,
    "return.md": Scene.RETURN,
    "logistics.md": Scene.LOGISTICS,
    "quality.md": Scene.QUALITY,
}


def parse_args() -> argparse.Namespace:
    """解析政策目录参数。"""

    parser = argparse.ArgumentParser(description="初始化 AC-py 演示数据")
    parser.add_argument("--policies", type=Path, default=Path("data/policies"))
    return parser.parse_args()


async def seed_business(database: Database) -> int:
    """插入一组可供诊断工具查询的订单、退款、物流和工单数据。"""

    async with database.session_factory() as session:
        existing = (
            await session.scalars(select(Ticket).where(Ticket.description == "退款一直没到账"))
        ).first()
        if existing is not None:
            return existing.id
        customer = Customer(name="演示客户")
        product = Product(sku="DEMO-CUP-001", name="保温杯", category="home")
        session.add_all([customer, product])
        await session.flush()
        order = Order(
            order_no="AC202607200001",
            customer_id=customer.id,
            product_id=product.id,
            status="refunding",
            amount=12900,
        )
        session.add(order)
        await session.flush()
        session.add_all(
            [
                Refund(
                    order_id=order.id,
                    status="approved",
                    reason="用户取消订单",
                    amount=12900,
                    timeline=[{"status": "approved", "time": "2026-07-18T10:00:00"}],
                ),
                Logistics(
                    order_id=order.id,
                    tracking_no="DEMO10001",
                    status="returned",
                    events=[{"status": "returned", "time": "2026-07-18T08:00:00"}],
                ),
            ]
        )
        ticket = Ticket(
            order_id=order.id,
            customer_id=customer.id,
            status="open",
            description="退款一直没到账",
            scene=Scene.REFUND.value,
        )
        session.add(ticket)
        await session.flush()
        session.add(
            TicketRecord(
                ticket_id=ticket.id,
                operator="customer",
                action="create",
                content=ticket.description,
            )
        )
        await session.commit()
        return ticket.id


async def index_policies(policy_dir: Path) -> tuple[str, int]:
    """切分四类本地政策并构建、发布一个版本化索引。"""

    settings = get_settings()
    elasticsearch = AsyncElasticsearch(settings.elasticsearch_url)
    model = OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        settings.embedding_model,
        settings.rerank_model,
    )
    chunks = []
    try:
        for file_name, scene in POLICY_SCENES.items():
            path = policy_dir / file_name
            chunks.extend(
                split_policy(
                    document_id=path.stem,
                    version="v1",
                    title=path.stem,
                    text=path.read_text(encoding="utf-8"),
                    scene=scene,
                )
            )
        indexer = PolicyIndexer(elasticsearch, model, settings)
        index_name = await indexer.build(chunks)
        await indexer.publish(index_name)
        return index_name, len(chunks)
    finally:
        await model.close()
        await elasticsearch.close()


async def run(policy_dir: Path) -> dict[str, object]:
    """依次初始化数据库演示数据和政策检索索引。"""

    settings = get_settings()
    database = Database(settings)
    try:
        await database.create_schema()
        ticket_id = await seed_business(database)
        index_name, chunk_count = await index_policies(policy_dir)
        return {"ticket_id": ticket_id, "index_name": index_name, "chunks": chunk_count}
    finally:
        await database.close()


def main() -> None:
    """执行演示环境初始化并打印非敏感结果。"""

    args = parse_args()
    print(asyncio.run(run(args.policies)))


if __name__ == "__main__":
    main()
