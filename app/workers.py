"""后台线程封装：把耗时操作（数据库查询等）放到 QThread，避免卡住界面。"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal


class FunctionWorker(QThread):
    """在后台线程执行一个 callable，通过信号回传结果。

    callable 形如 ``fn(progress_cb) -> object``：
    - ``progress_cb(text)`` 用于汇报进度（主线程更新界面）；
    - 返回值经 ``succeeded`` 信号送出；异常经 ``failed`` 信号送出。
    """

    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):  # noqa: D401 - QThread 入口
        try:
            result = self._fn(self.progress.emit)
        except Exception as exc:  # noqa: BLE001 - 统一把异常转成错误信号
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)
