"""读取 JSONL 评测集并校验售后场景和相关政策标签。"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from ac_py.domain.enums import Scene


class EvalCase(BaseModel):
    """表示一条可用于路由与检索实验的标注样例。"""

    case_id: str
    query: str
    context: str = ""
    scene: Scene
    relevant_titles: set[str] = Field(default_factory=set)


def load_cases(path: Path) -> list[EvalCase]:
    """从 JSONL 文件读取评测样例。"""

    cases: list[EvalCase] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                cases.append(EvalCase.model_validate(json.loads(line)))
    return cases
