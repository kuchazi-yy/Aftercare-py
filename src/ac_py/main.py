"""创建 FastAPI 应用并提供命令行启动入口。"""

import uvicorn
from fastapi import FastAPI

from ac_py.api.routes import router
from ac_py.config import get_settings
from ac_py.observability.metrics import PrometheusMiddleware
from ac_py.runtime import lifespan


def create_app() -> FastAPI:
    """创建配置了生命周期、监控和业务路由的 FastAPI 应用。"""

    app = FastAPI(
        title="AC-py 售后工单智能诊断系统",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(PrometheusMiddleware)
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()


def run() -> None:
    """使用配置中的监听地址启动 Uvicorn。"""

    settings = get_settings()
    uvicorn.run("ac_py.main:app", host=settings.app_host, port=settings.app_port, reload=False)
