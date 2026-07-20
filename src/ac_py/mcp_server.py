"""通过标准输入输出暴露 14 个业务工具，供外部 MCP Client 调用。"""

import json

import anyio
from mcp import types
from mcp.server import InitializationOptions, NotificationOptions, Server
from mcp.server.stdio import stdio_server

from ac_py.cache.store import RedisStateStore
from ac_py.config import get_settings
from ac_py.db.base import Database
from ac_py.db.repositories import BusinessRepository
from ac_py.domain.schemas import ToolCall
from ac_py.tools.builtin import create_business_registry
from ac_py.tools.executor import ToolExecutor

server = Server("ac-business-tools")
executor: ToolExecutor | None = None


@server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
async def list_tools() -> list[types.Tool]:
    """向 MCP Client 返回注册表中的完整工具 Schema。"""

    if executor is None:
        raise RuntimeError("MCP Server 尚未初始化")
    tools: list[types.Tool] = []
    for manifest in executor.registry.manifests():
        registered = executor.registry.get(manifest.name)
        if registered is None:
            raise RuntimeError(f"工具清单与注册表不一致: {manifest.name}")
        tools.append(
            types.Tool(
                name=manifest.name,
                title=manifest.name,
                description=manifest.description,
                inputSchema=registered.spec.input_schema,
            )
        )
    return tools


@server.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(
    name: str,
    arguments: dict[str, object] | None,
) -> list[types.TextContent]:
    """通过统一执行器调用工具并返回 JSON 文本结果。"""

    if executor is None:
        raise RuntimeError("MCP Server 尚未初始化")
    result = await executor.execute(
        ToolCall(name=name, arguments=dict(arguments or {})),
        run_id="mcp",
        permissions={"ticket:read", "ticket:transfer", "refund:write", "return:write"},
    )
    return [
        types.TextContent(type="text", text=json.dumps(result.model_dump(), ensure_ascii=False))
    ]


async def serve() -> None:
    """初始化数据库与 Redis，并启动 stdio MCP Server。"""

    global executor
    settings = get_settings()
    database = Database(settings)
    store = RedisStateStore(settings.redis_url)
    registry = create_business_registry(BusinessRepository(database.session_factory))
    executor = ToolExecutor(registry, store, business_cache_seconds=settings.cache_business_seconds)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="ac-business-tools",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    finally:
        await store.close()
        await database.close()


def main() -> None:
    """使用 AnyIO 启动 MCP Server。"""

    anyio.run(serve)


if __name__ == "__main__":
    main()
