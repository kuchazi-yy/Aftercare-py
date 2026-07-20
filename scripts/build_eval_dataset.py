"""从 JDDC 官方动作标签中抽取 200 条中文售后评测样例。"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from ac_py.domain.enums import Scene

csv.field_size_limit(10 * 1024 * 1024)

LABELS: dict[str, tuple[Scene, str]] = {
    "正常退款周期": (Scene.REFUND, "退款到账时效"),
    "退款到哪儿": (Scene.REFUND, "退款到账时效"),
    "申请退款": (Scene.REFUND, "退款申请条件"),
    "退款异常": (Scene.REFUND, "退款异常处理"),
    "保修返修及退换货政策": (Scene.RETURN, "七天无理由退货"),
    "售后运费": (Scene.RETURN, "退货运费"),
    "返修退换货处理周期": (Scene.RETURN, "退货处理周期"),
    "配送周期": (Scene.LOGISTICS, "配送时效"),
    "物流全程跟踪": (Scene.LOGISTICS, "物流轨迹停滞"),
    "联系配送": (Scene.LOGISTICS, "物流轨迹停滞"),
    "少商品与少配件": (Scene.QUALITY, "商品少件"),
    "物流损": (Scene.QUALITY, "商品破损"),
    "外包装": (Scene.QUALITY, "商品破损"),
}


def parse_args() -> argparse.Namespace:
    """解析源数据和输出文件路径。"""

    parser = argparse.ArgumentParser(description="构建 AC-py 评测数据集")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def build_cases(source: Path, per_scene: int = 50) -> list[dict[str, object]]:
    """按场景均衡抽取用户话术，并保留同会话最近上下文。"""

    scene_counts: Counter[Scene] = Counter()
    title_counts: Counter[str] = Counter()
    seen: set[str] = set()
    cases: list[dict[str, object]] = []
    title_limit = 25
    history: list[str] = []
    with source.open("r", encoding="utf-8") as file:
        reader = csv.reader(file, delimiter="\t")
        for row in reader:
            if not row:
                history = []
                continue
            if len(row) < 2:
                continue
            role, query = row[0], row[1].strip()
            if role == "USER" and len(row) >= 3 and row[2] in LABELS:
                scene, title = LABELS[row[2]]
                eligible = (
                    query
                    and query not in seen
                    and scene_counts[scene] < per_scene
                    and title_counts[title] < title_limit
                )
                if eligible:
                    seen.add(query)
                    scene_counts[scene] += 1
                    title_counts[title] += 1
                    cases.append(
                        {
                            "case_id": f"jddc-{len(cases) + 1:03d}",
                            "query": query,
                            "context": "\n".join(history[-8:]),
                            "scene": scene.value,
                            "relevant_titles": [title],
                        }
                    )
            if role in {"USER", "SYSTEM"} and query != "OVERALL":
                history.append(f"{role}: {query}")
    expected = per_scene * len(Scene.__members__) - per_scene
    if len(cases) != expected:
        raise RuntimeError(f"评测数据不足，期望 {expected} 条，实际 {len(cases)} 条")
    return cases


def write_cases(cases: list[dict[str, object]], output: Path) -> None:
    """以 UTF-8 JSONL 格式写入评测样例。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        for case in cases:
            file.write(json.dumps(case, ensure_ascii=False) + "\n")


def main() -> None:
    """执行数据抽取并输出样例数量。"""

    args = parse_args()
    cases = build_cases(args.source)
    write_cases(cases, args.output)
    print(f"已生成 {len(cases)} 条评测样例: {args.output}")


if __name__ == "__main__":
    main()
