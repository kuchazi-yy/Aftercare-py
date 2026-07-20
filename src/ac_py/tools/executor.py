"""执行场景工具，统一处理权限、参数校验、缓存、重试、超时和审计。"""

import asyncio
import time

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]

from ac_py.cache.store import StateStore
from ac_py.db.repositories import DiagnosisRepository
from ac_py.domain.enums import RiskLevel
from ac_py.domain.schemas import ToolCall, ToolResult
from ac_py.tools.registry import RegisteredTool, ToolRegistry


class ToolExecutor:
    """作为 Agent 调用业务工具的唯一入口。"""

    def __init__(
        self,
        registry: ToolRegistry,
        state_store: StateStore,
        diagnosis_repository: DiagnosisRepository | None = None,
        business_cache_seconds: int = 30,
    ) -> None:
        """保存工具注册表、短期状态存储和可选审计仓储。"""

        self.registry = registry
        self.state_store = state_store
        self.diagnosis_repository = diagnosis_repository
        self.business_cache_seconds = business_cache_seconds

    async def execute(
        self,
        call: ToolCall,
        run_id: str,
        permissions: set[str],
        *,
        approved: bool = False,
    ) -> ToolResult:
        """校验并执行工具，高风险工具仅在显式批准后产生副作用。"""

        started = time.perf_counter()
        tool = self.registry.get(call.name)
        if tool is None:
            return self._error(call.name, started, "工具不存在")
        if tool.spec.required_permission not in permissions:
            return self._error(call.name, started, "没有工具调用权限")
        try:
            validate(instance=call.arguments, schema=tool.spec.input_schema)
        except ValidationError as exc:
            return self._error(call.name, started, f"参数校验失败: {exc.message}")

        if tool.spec.risk_level == RiskLevel.HIGH and not approved:
            result = ToolResult(
                name=call.name,
                ok=True,
                data={
                    "approval_required": True,
                    "action": call.name,
                    "payload": call.arguments,
                },
                latency_ms=self._latency_ms(started),
            )
            await self._audit(run_id, call, result)
            return result

        if tool.spec.risk_level == RiskLevel.HIGH:
            return await self._execute_approved_write(tool, call, run_id, started)

        cache_key = self._cache_key(call)
        cached = await self.state_store.get_json(cache_key)
        if cached is not None and tool.spec.risk_level == RiskLevel.READ:
            result = ToolResult(
                name=call.name,
                ok=True,
                data=cached,
                cached=True,
                latency_ms=self._latency_ms(started),
            )
            await self._audit(run_id, call, result)
            return result

        result = await self._run_with_retry(tool, call, started)
        if result.ok and tool.spec.risk_level == RiskLevel.READ:
            await self.state_store.set_json(
                cache_key,
                result.data,
                self.business_cache_seconds,
            )
        await self._audit(run_id, call, result)
        return result

    async def _execute_approved_write(
        self,
        tool: RegisteredTool,
        call: ToolCall,
        run_id: str,
        started: float,
    ) -> ToolResult:
        """使用幂等键串行执行已批准的高风险写工具。"""

        if not call.idempotency_key:
            return self._error(call.name, started, "高风险工具缺少幂等键")
        result_key = f"idempotency:{call.idempotency_key}"
        cached = await self.state_store.get_json(result_key)
        if cached is not None:
            return ToolResult.model_validate(cached)
        async with self.state_store.lock(result_key, 10) as acquired:
            if not acquired:
                return self._error(call.name, started, "相同业务动作正在执行")
            cached = await self.state_store.get_json(result_key)
            if cached is not None:
                return ToolResult.model_validate(cached)
            result = await self._run_with_retry(tool, call, started)
            if result.ok:
                await self.state_store.set_json(result_key, result.model_dump(mode="json"), 86400)
            await self._audit(run_id, call, result)
            return result

    async def execute_many(
        self,
        calls: list[ToolCall],
        run_id: str,
        permissions: set[str],
    ) -> list[ToolResult]:
        """并发执行读工具，并按顺序执行包含副作用的工具。"""

        read_calls: list[ToolCall] = []
        write_calls: list[ToolCall] = []
        for call in calls:
            tool = self.registry.get(call.name)
            if tool is not None and tool.spec.risk_level == RiskLevel.READ:
                read_calls.append(call)
            else:
                write_calls.append(call)

        results = list(
            await asyncio.gather(*(self.execute(call, run_id, permissions) for call in read_calls))
        )
        for call in write_calls:
            results.append(await self.execute(call, run_id, permissions))
        return results

    async def _run_with_retry(
        self,
        tool: RegisteredTool,
        call: ToolCall,
        started: float,
    ) -> ToolResult:
        """在超时限制内执行工具，并对读工具进行有限重试。"""

        error = "工具执行失败"
        for attempt in range(tool.spec.max_retries + 1):
            try:
                data = await asyncio.wait_for(
                    tool.handler(call.arguments),
                    timeout=tool.spec.timeout_seconds,
                )
                return ToolResult(
                    name=call.name,
                    ok=True,
                    data=data,
                    latency_ms=self._latency_ms(started),
                )
            except TimeoutError:
                error = "工具调用超时"
            except Exception as exc:  # noqa: BLE001
                error = f"工具执行异常: {type(exc).__name__}"
            if attempt < tool.spec.max_retries:
                await asyncio.sleep(0.05 * (attempt + 1))
        return self._error(call.name, started, error)

    async def _audit(self, run_id: str, call: ToolCall, result: ToolResult) -> None:
        """在配置审计仓储时保存工具轨迹。"""

        if self.diagnosis_repository is not None:
            await self.diagnosis_repository.log_tool(run_id, result, call.arguments)

    @staticmethod
    def _cache_key(call: ToolCall) -> str:
        """根据工具名称和稳定参数生成短期缓存键。"""

        ticket_id = call.arguments.get("ticket_id", "unknown")
        return f"tool:{call.name}:ticket:{ticket_id}"

    @staticmethod
    def _latency_ms(started: float) -> int:
        """计算从开始时间到当前时刻的毫秒耗时。"""

        return int((time.perf_counter() - started) * 1000)

    @classmethod
    def _error(cls, name: str, started: float, error: str) -> ToolResult:
        """创建统一错误结果。"""

        return ToolResult(
            name=name,
            ok=False,
            error=error,
            latency_ms=cls._latency_ms(started),
        )
