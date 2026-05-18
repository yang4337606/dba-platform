"""
简单的后台任务管理器
使用线程池实现异步分析，即使用户关闭页面也能继续执行
"""
import threading
import uuid
from datetime import datetime
from typing import Dict, Callable
import logging

logger = logging.getLogger(__name__)


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    def __init__(self, task_id: str, name: str, func: Callable, args: tuple, kwargs: dict):
        self.task_id = task_id
        self.name = name
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.progress = 0

    def run(self):
        """执行任务"""
        try:
            self.status = TaskStatus.RUNNING
            self.started_at = datetime.now()
            logger.info("Task %s started: %s", self.task_id, self.name)

            self.result = self.func(*self.args, **self.kwargs)

            self.status = TaskStatus.COMPLETED
            self.completed_at = datetime.now()
            self.progress = 100
            logger.info("Task %s completed", self.task_id)

        except Exception as e:
            self.status = TaskStatus.FAILED
            self.error = str(e)
            self.completed_at = datetime.now()
            logger.error("Task %s failed: %s", self.task_id, e, exc_info=True)

    def to_dict(self):
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }


class TaskManager:
    """简单的任务管理器"""

    def __init__(self, max_workers=3):
        self.tasks: Dict[str, Task] = {}
        self.max_workers = max_workers
        self._lock = threading.Lock()

    def submit(self, name: str, func: Callable, *args, **kwargs) -> str:
        """提交一个新任务"""
        with self._lock:
            self.cleanup_old_tasks()

            # Enforce max_workers limit
            running_count = sum(
                1 for t in self.tasks.values()
                if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            )
            if running_count >= self.max_workers:
                raise RuntimeError(
                    f"已达到最大并发任务数 ({self.max_workers})，请等待现有任务完成"
                )

            task_id = str(uuid.uuid4())
            task = Task(task_id, name, func, args, kwargs)
            self.tasks[task_id] = task

        # 在新线程中执行任务（在锁外启动，避免死锁）
        thread = threading.Thread(target=task.run, daemon=True)
        thread.start()

        logger.info("Task %s submitted: %s", task_id, name)
        return task_id

    def get_task(self, task_id: str) -> Task:
        """获取任务"""
        with self._lock:
            return self.tasks.get(task_id)

    def get_all_tasks(self) -> list:
        """获取所有任务"""
        with self._lock:
            return [task.to_dict() for task in self.tasks.values()]

    def cleanup_old_tasks(self, max_age_hours=24):
        """清理旧任务 (caller must hold self._lock)."""
        now = datetime.now()
        to_remove = []
        for task_id, task in self.tasks.items():
            if task.completed_at:
                age = (now - task.completed_at).total_seconds() / 3600
                if age > max_age_hours:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self.tasks[task_id]
            logger.info("Cleaned up old task: %s", task_id)


# 全局任务管理器实例
task_manager = TaskManager(max_workers=3)
