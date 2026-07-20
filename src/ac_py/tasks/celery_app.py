"""创建 Celery 应用并配置 Redis Broker 与结果存储。"""

from celery import Celery  # type: ignore[import-untyped]

from ac_py.config import get_settings

settings = get_settings()
celery_app = Celery(
    "ac_py",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["ac_py.tasks.jobs"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=86400,
)
