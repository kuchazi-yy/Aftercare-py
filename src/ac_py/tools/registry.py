"""维护工具目录，并按售后场景渐进式披露工具定义。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ac_py.domain.enums import RiskLevel, Scene
from ac_py.domain.schemas import ToolManifest, ToolSpec

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class RegisteredTool:
    """把工具约束与实际异步处理函数绑定在一起。"""

    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    """集中管理本地及 MCP 工具，并提供场景级工具筛选。"""

    def __init__(self) -> None:
        """初始化空工具仓储。"""

        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        """注册工具，同名工具需要显式注销后才能替换。"""

        if tool.spec.name in self._tools:
            raise ValueError(f"工具已存在: {tool.spec.name}")
        self._tools[tool.spec.name] = tool

    def unregister(self, name: str) -> None:
        """注销指定工具。"""

        self._tools.pop(name, None)

    def get(self, name: str) -> RegisteredTool | None:
        """按名称返回完整工具定义。"""

        return self._tools.get(name)

    def manifests(self) -> list[ToolManifest]:
        """返回全部工具的轻量 Manifest，不暴露完整参数 Schema。"""

        return [
            ToolManifest.model_validate(tool.spec.model_dump()) for tool in self._tools.values()
        ]

    def specs_for_scenes(self, scenes: set[Scene], max_tools: int = 9) -> list[ToolSpec]:
        """按场景筛选完整工具定义，并限制注入模型的工具数量。"""

        matched = [
            tool.spec
            for tool in self._tools.values()
            if Scene.OTHER in tool.spec.scenes or bool(tool.spec.scenes & scenes)
        ]
        matched.sort(key=lambda spec: (spec.risk_level != RiskLevel.READ, spec.name))
        return matched[:max_tools]

    @property
    def count(self) -> int:
        """返回当前已注册工具数量。"""

        return len(self._tools)

    @property
    def names(self) -> list[str]:
        """返回稳定排序的工具名称。"""

        return sorted(self._tools)
