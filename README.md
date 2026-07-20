# AC-py 电商售后工单智能诊断系统

AC-py 使用 FastAPI 和 LangGraph 构建受控售后诊断流程。业务事实通过场景化工具查询，政策知识由 Elasticsearch 完成 BM25 与 dense kNN 混合召回，最终回复只使用最新业务状态和精排后的 Top3 政策证据。

## 核心设计

- 确定性状态图：场景识别、工具查询、检索、证据校验、生成和人工审批均为独立节点。
- 渐进式上下文：先选择场景和工具，再加载完整 Schema、条款及父章节。
- 分层 Memory：Redis 保存短期工作状态，MySQL 保存长期事实和审计，Elasticsearch 保存政策知识。
- 延迟治理：工具并发、单次主要模型调用、6000 Token 上限、Top3 证据和 SSE 流式输出。
- 可验证优化：所有切分、候选规模、工具过滤、Memory 和缓存优化均通过离线实验比较。

## 快速启动

```powershell
Copy-Item .env.example .env
# 在 .env 中填写 LLM_API_KEY 与 LLM_MODEL
docker compose up -d --build
docker compose run --rm api python scripts/bootstrap_demo.py
```

API 文档：`http://localhost:8080/docs`

Prometheus：`http://localhost:9090`

健康检查：`http://localhost:8080/api/v1/health`

## 已验证结果

当前结果基于 24 个政策父/子块与 200 条 JDDC 动作标注样例，不代表大规模生产知识库：

- 冷检索 P50/P95：223ms/254ms；Redis 热缓存：1.69ms/2.06ms。
- 20 次 SSE 热路径：首事件 P95 5.08ms，TTFT P50/P95 484ms/2.73s。
- 场景过滤将工具 Schema 从 1566 Token 降至平均 690 Token，减少 56.0%。
- 1000 至 8000 输入 Token 下，模型 TTFT P50 从 393ms 增至 1090ms。

完整口径与限制见 [实验报告](docs/experiments.md)，技术选型见 [架构设计](docs/architecture.md)。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src scripts
```

需要解析 PDF、Word 或扫描件时额外安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[documents]"
```

## 评测命令

```powershell
.\.venv\Scripts\ac-eval.exe data\eval_cases.jsonl --retrieval
.\.venv\Scripts\python.exe scripts\benchmark_latency.py api --repeats 20
.\.venv\Scripts\python.exe scripts\benchmark_latency.py model --repeats 20
```
