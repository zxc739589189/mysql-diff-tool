"""单个「数据对比」标签页：数据源配置、SQL 编辑、字段过滤、结果展示。

每个标签页持有自己独立的配置与查询结果，互不影响。
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .compare import (
    STATUS_DIFF,
    STATUS_ONLY_A,
    STATUS_ONLY_B,
    STATUS_SAME,
    STATUS_TEXT,
    CompareResult,
    compare_results,
    resolve_compare_key,
)
from .config import (
    DataSourceConfig,
    TabConfig,
    default_config_dir,
    load_tab_config,
    save_tab_config,
)
from .db import run_query, test_connection
from .workers import FunctionWorker

MAX_DISPLAY_ROWS = 5000  # 表格最多展示的行数（防止大数据量卡界面）

# ── 结果表格配色（低刺激、突出差异）──
# 设计：完全一致不染色；差异值浅红底+深红粗体；状态列只用彩色粗体文字
DIFF_VALUE_BG = QColor("#fdecea")    # 差异值浅红底
DIFF_VALUE_FG = QColor("#c62828")    # 差异值深红粗体
ONLY_KEY_BG = {
    STATUS_ONLY_A: QColor("#fff7e6"),  # 仅 A:key 单元格浅黄
    STATUS_ONLY_B: QColor("#e8f1fd"),  # 仅 B:key 单元格浅蓝
}
STATUS_FG = {
    STATUS_DIFF: QColor("#c62828"),    # 红字
    STATUS_ONLY_A: QColor("#b26a00"),  # 琥珀字
    STATUS_ONLY_B: QColor("#1565c0"),  # 蓝字
    STATUS_SAME: QColor("#2e7d32"),    # 绿字
}

# 结果过滤下拉框选项：(显示文本, 保留的状态集合, None 表示全部)
FILTER_OPTIONS = [
    ("全部", None),
    ("仅看差异", (STATUS_DIFF, STATUS_ONLY_A, STATUS_ONLY_B)),
    ("值不一致", (STATUS_DIFF,)),
    ("仅 A 存在", (STATUS_ONLY_A,)),
    ("仅 B 存在", (STATUS_ONLY_B,)),
    ("完全一致", (STATUS_SAME,)),
]


def full_text(value: object) -> str:
    """把任意数据库值转成完整文本（不截断），用于复制与 tooltip。"""
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + bytes(value).hex()
    return str(value)


def display_text(value: object, limit: int = 0) -> str:
    """表格展示文本：不截断（超长部分在单元格边缘自然裁剪，复制不受影响）。"""
    return full_text(value)


class CompareTab(QWidget):
    """一个完整、独立的对比标签页。"""

    title_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._closing = False
        self._worker: Optional[FunctionWorker] = None
        self._path_user_edited = False          # 用户是否手动改过配置路径
        self._pinned_filters: List[str] = []    # 已固定到配置的过滤字段
        self._checkboxes: Dict[str, QCheckBox] = {}
        self._suppress_filter_events = False
        self._data: Optional[Tuple[list, list, list, list]] = None  # 查询结果缓存
        self._result: Optional[CompareResult] = None
        self._stale = False  # SQL/连接信息在对比后被修改,结果已过期
        self._build_ui()
        self._connect_signals()
        self._update_default_config_path()

    # ───────────────────────── 界面搭建 ─────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 配置文件栏
        cfg_bar = QHBoxLayout()
        cfg_bar.addWidget(QLabel("配置文件:"))
        self.config_path_edit = QLineEdit()
        self.config_path_edit.setPlaceholderText("固定地址的 JSON 配置文件路径")
        cfg_bar.addWidget(self.config_path_edit, 1)
        self.btn_browse = QPushButton("浏览…")
        self.btn_load_cfg = QPushButton("读取配置")
        self.btn_save_cfg = QPushButton("保存配置")
        cfg_bar.addWidget(self.btn_browse)
        cfg_bar.addWidget(self.btn_load_cfg)
        cfg_bar.addWidget(self.btn_save_cfg)
        root.addLayout(cfg_bar)

        # 任务名 / key 字段
        meta_bar = QHBoxLayout()
        meta_bar.addWidget(QLabel("任务名:"))
        self.task_edit = QLineEdit()
        self.task_edit.setPlaceholderText("同时作为标签页标题与默认配置文件名")
        meta_bar.addWidget(self.task_edit, 1)
        meta_bar.addSpacing(12)
        meta_bar.addWidget(QLabel("对齐 key 字段:"))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("留空默认第一列；填 (行号) 按行顺序对比")
        self.key_edit.setFixedWidth(220)
        meta_bar.addWidget(self.key_edit)
        root.addLayout(meta_bar)

        # 数据源 A / B
        ds_splitter = QSplitter(Qt.Horizontal)
        self.ds_a = self._make_ds_group("数据源 A")
        self.ds_b = self._make_ds_group("数据源 B")
        ds_splitter.addWidget(self.ds_a["group"])
        ds_splitter.addWidget(self.ds_b["group"])
        root.addWidget(ds_splitter)

        # SQL A / B
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        sql_splitter = QSplitter(Qt.Horizontal)
        group_a = QGroupBox("数据源 A 查询 SQL")
        lay_a = QVBoxLayout(group_a)
        self.sql_a = QPlainTextEdit()
        self.sql_a.setFont(mono)
        self.sql_a.setPlaceholderText("SELECT ... FROM ... WHERE <A 环境条件>")
        lay_a.addWidget(self.sql_a)
        group_b = QGroupBox("数据源 B 查询 SQL")
        lay_b = QVBoxLayout(group_b)
        self.sql_b = QPlainTextEdit()
        self.sql_b.setFont(mono)
        self.sql_b.setPlaceholderText("SELECT ... FROM ... WHERE <B 环境条件>")
        lay_b.addWidget(self.sql_b)
        sql_splitter.addWidget(group_a)
        sql_splitter.addWidget(group_b)
        root.addWidget(sql_splitter, 1)

        # 操作栏
        action_bar = QHBoxLayout()
        self.btn_copy_ab = QPushButton("复制 A 的 SQL 到 B →")
        self.btn_compare = QPushButton("开始对比")
        self.btn_compare.setStyleSheet("font-weight: bold; padding: 4px 18px;")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(160)
        self.progress.setRange(0, 0)  # 忙碌指示
        self.progress.setVisible(False)
        self.run_status = QLabel("就绪")
        self.run_status.setStyleSheet("color: gray;")
        action_bar.addWidget(self.btn_copy_ab)
        action_bar.addStretch(1)
        action_bar.addWidget(self.run_status)
        action_bar.addWidget(self.progress)
        action_bar.addWidget(self.btn_compare)
        root.addLayout(action_bar)

        # 统计栏
        stats_bar = QHBoxLayout()
        self.stat_labels: Dict[str, QLabel] = {}
        stat_items = [
            ("a_rows", "A 行数"),
            ("b_rows", "B 行数"),
            ("common", "共同 key"),
            ("only_a", "仅 A"),
            ("only_b", "仅 B"),
            ("diff", "有差异 key"),
            ("same", "完全一致 key"),
        ]
        for i, (key, text) in enumerate(stat_items):
            if i:
                stats_bar.addWidget(self._vline())
            lab = QLabel("%s: -" % text)
            lab.setTextFormat(Qt.RichText)
            self.stat_labels[key] = lab
            stats_bar.addWidget(lab)
        stats_bar.addStretch(1)
        root.addLayout(stats_bar)
        self._stat_names = dict(stat_items)

        # 字段过滤区
        filter_group = QGroupBox("字段过滤（取消勾选 = 该字段不参与对比）")
        fg = QVBoxLayout(filter_group)
        btn_row = QHBoxLayout()
        self.btn_all = QPushButton("全选")
        self.btn_none = QPushButton("全不选")
        self.btn_pin = QPushButton("固定到配置")
        hint = QLabel("提示：临时勾选仅本次有效；「固定到配置」会把当前未勾选字段写入配置文件")
        hint.setStyleSheet("color: gray;")
        btn_row.addWidget(self.btn_all)
        btn_row.addWidget(self.btn_none)
        btn_row.addWidget(self.btn_pin)
        btn_row.addWidget(hint, 1)
        fg.addLayout(btn_row)
        self.filter_area = QScrollArea()
        self.filter_area.setWidgetResizable(True)
        self.filter_area.setFixedHeight(84)
        self.filter_host = QWidget()
        self.filter_grid = QGridLayout(self.filter_host)
        self.filter_grid.setContentsMargins(4, 2, 4, 2)
        self.filter_grid.setSpacing(4)
        self.filter_area.setWidget(self.filter_host)
        fg.addWidget(self.filter_area)
        root.addWidget(filter_group)

        # 对比结论(独立模块:按 key 直接输出哪些字段值不同)
        self.diff_group = QGroupBox("对比结论(哪些 key 不一样、差在哪些字段)")
        dg = QVBoxLayout(self.diff_group)
        self.diff_text = QPlainTextEdit()
        self.diff_text.setReadOnly(True)
        self.diff_text.setFont(mono)
        self.diff_text.setMaximumHeight(150)
        self.diff_text.setPlaceholderText("执行对比后，这里直接输出结论")
        dg.addWidget(self.diff_text)
        self.diff_group.setVisible(False)  # 首次对比出结果后显示
        root.addWidget(self.diff_group)

        # 结果过滤栏
        res_bar = QHBoxLayout()
        res_bar.addWidget(QLabel("结果过滤:"))
        self.result_filter = QComboBox()
        for text, _ in FILTER_OPTIONS:
            self.result_filter.addItem(text)
        self.result_filter.setCurrentIndex(1)  # 默认「仅看差异」
        res_bar.addWidget(self.result_filter)
        self.result_count = QLabel("")
        self.result_count.setStyleSheet("color: gray;")
        res_bar.addWidget(self.result_count, 1)
        root.addLayout(res_bar)

        # 结果表格
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Key", "字段名", "A 值", "B 值", "状态"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self._setup_table_copy()
        root.addWidget(self.table, 2)

    @staticmethod
    def _vline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _make_ds_group(self, title: str) -> Dict[str, QWidget]:
        group = QGroupBox(title)
        form = QFormLayout(group)
        host = QLineEdit()
        host.setPlaceholderText("例如 127.0.0.1")
        port = QLineEdit("3306")
        port.setFixedWidth(90)
        user = QLineEdit()
        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        database = QLineEdit()

        host_row = QWidget()
        hr = QHBoxLayout(host_row)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.addWidget(host, 1)
        hr.addWidget(QLabel("端口:"))
        hr.addWidget(port)
        form.addRow("主机:", host_row)
        form.addRow("用户名:", user)
        form.addRow("密码:", password)
        form.addRow("数据库:", database)

        bottom = QWidget()
        br = QHBoxLayout(bottom)
        br.setContentsMargins(0, 0, 0, 0)
        btn_test = QPushButton("测试连接")
        status = QLabel("")
        status.setStyleSheet("color: gray;")
        br.addWidget(btn_test)
        br.addWidget(status, 1)
        form.addRow(bottom)

        widgets = {
            "group": group,
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "btn_test": btn_test,
            "status": status,
        }
        btn_test.clicked.connect(lambda: self.test_connection(widgets))
        return widgets

    def _connect_signals(self):
        self.btn_browse.clicked.connect(self.browse_config_path)
        self.btn_load_cfg.clicked.connect(self.load_config)
        self.btn_save_cfg.clicked.connect(self.save_config)
        self.btn_copy_ab.clicked.connect(
            lambda: self.sql_b.setPlainText(self.sql_a.toPlainText())
        )
        self.btn_compare.clicked.connect(self.start_compare)
        self.btn_all.clicked.connect(lambda: self._set_all_filters(True))
        self.btn_none.clicked.connect(lambda: self._set_all_filters(False))
        self.btn_pin.clicked.connect(self.pin_filters)
        self.result_filter.currentIndexChanged.connect(lambda *_: self._render_result())
        self.task_edit.textChanged.connect(self._on_task_name_changed)
        self.config_path_edit.textEdited.connect(self._on_path_edited)
        # SQL/连接信息变更 → 标记结果过期;key 变更 → 立即用缓存重算
        self.sql_a.textChanged.connect(self._mark_results_stale)
        self.sql_b.textChanged.connect(self._mark_results_stale)
        self.key_edit.editingFinished.connect(self._on_key_changed)
        for w in (self.ds_a, self.ds_b):
            for name in ("host", "port", "user", "password", "database"):
                w[name].textEdited.connect(self._mark_results_stale)

    # ───────────────────────── 配置读写 ─────────────────────────

    def task_name(self) -> str:
        return self.task_edit.text().strip()

    def set_task_name(self, name: str):
        self.task_edit.setText(name)

    def _on_task_name_changed(self, text: str):
        self.title_changed.emit(text.strip() or "未命名")
        if not self._path_user_edited:
            self._update_default_config_path()

    def _on_path_edited(self, *_):
        self._path_user_edited = True

    def _update_default_config_path(self):
        name = re.sub(r'[\\/:*?"<>|]+', "_", self.task_name()) or "未命名"
        self.config_path_edit.setText(os.path.join(default_config_dir(), name + ".json"))

    def _ds_config(self, w: Dict[str, QWidget]) -> DataSourceConfig:
        try:
            port = int(w["port"].text().strip() or "3306")
        except ValueError:
            port = 3306
        return DataSourceConfig(
            host=w["host"].text().strip(),
            port=port,
            user=w["user"].text().strip(),
            password=w["password"].text(),
            database=w["database"].text().strip(),
        )

    @staticmethod
    def _set_ds_config(w: Dict[str, QWidget], cfg: DataSourceConfig):
        w["host"].setText(cfg.host)
        w["port"].setText(str(cfg.port))
        w["user"].setText(cfg.user)
        w["password"].setText(cfg.password)
        w["database"].setText(cfg.database)

    def get_config(self) -> TabConfig:
        """收集当前 tab 的配置（过滤字段只保存「已固定」的部分）。"""
        return TabConfig(
            task_name=self.task_name(),
            source_a=self._ds_config(self.ds_a),
            source_b=self._ds_config(self.ds_b),
            sql_a=self.sql_a.toPlainText(),
            sql_b=self.sql_b.toPlainText(),
            key_field=self.key_edit.text().strip(),
            fixed_filters=list(self._pinned_filters),
        )

    def set_config(self, cfg: TabConfig):
        """把配置填充到界面。"""
        self.task_edit.setText(cfg.task_name)
        self._set_ds_config(self.ds_a, cfg.source_a)
        self._set_ds_config(self.ds_b, cfg.source_b)
        self.sql_a.setPlainText(cfg.sql_a)
        self.sql_b.setPlainText(cfg.sql_b)
        self.key_edit.setText(cfg.key_field)
        self._pinned_filters = list(cfg.fixed_filters)
        if not self._path_user_edited:
            self._update_default_config_path()

    def browse_config_path(self):
        """打开文件对话框，直接选择已有的配置文件（不创建新文件）。"""
        start = self.config_path_edit.text().strip() or default_config_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "选择配置文件", start, "JSON 配置 (*.json);;所有文件 (*)"
        )
        if path:
            self.config_path_edit.setText(path)
            self._path_user_edited = True

    def load_config(self):
        path = self.config_path_edit.text().strip()
        if not path:
            self._warn("请先填写配置文件路径")
            return
        try:
            cfg = load_tab_config(path)
        except Exception as exc:
            self._error("读取配置失败：\n%s" % exc)
            return
        self.set_config(cfg)
        self.config_path_edit.setText(path)  # 保持当前使用的路径
        self._info("已读取配置：\n%s" % path)

    def save_config(self, show_message: bool = True) -> bool:
        path = self.config_path_edit.text().strip()
        if not path:
            self._warn("请先填写配置文件路径")
            return False
        try:
            save_tab_config(path, self.get_config())
        except Exception as exc:
            self._error("保存配置失败：\n%s" % exc)
            return False
        if show_message:
            self._info("配置已保存：\n%s" % path)
        return True

    # ───────────────────────── 连接测试 / 对比 ─────────────────────────

    def test_connection(self, w: Dict[str, QWidget]):
        cfg = self._ds_config(w)
        if not cfg.host:
            self._warn("请先填写主机地址")
            return
        w["btn_test"].setEnabled(False)
        w["status"].setText("正在连接…")
        w["status"].setStyleSheet("color: gray;")

        def job(_progress):
            return test_connection(cfg)

        worker = FunctionWorker(job, self)
        worker.succeeded.connect(
            lambda msg: (
                w["status"].setText("✓ " + msg),
                w["status"].setStyleSheet("color: green;"),
            )
        )
        worker.failed.connect(
            lambda err: (
                w["status"].setText("✗ 连接失败"),
                w["status"].setStyleSheet("color: red;"),
                self._error("连接失败：\n%s" % err),
            )
        )
        worker.finished.connect(lambda: w["btn_test"].setEnabled(True))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def start_compare(self):
        if self._worker is not None and self._worker.isRunning():
            self._warn("正在对比中，请稍候")
            return
        cfg_a = self._ds_config(self.ds_a)
        cfg_b = self._ds_config(self.ds_b)
        sql_a = self.sql_a.toPlainText().strip()
        sql_b = self.sql_b.toPlainText().strip()
        if not cfg_a.host or not cfg_b.host:
            self._warn("请先填写数据源 A / B 的主机地址")
            return
        if not sql_a or not sql_b:
            self._warn("请先填写数据源 A / B 的查询 SQL")
            return

        self._clear_results()  # 先清空旧结果,避免过期数字误导
        self._set_running(True, "开始查询…")

        def job(progress):
            progress("正在查询数据源 A …")
            cols_a, rows_a = run_query(cfg_a, sql_a)
            progress("数据源 A 返回 %d 行，正在查询数据源 B …" % len(rows_a))
            cols_b, rows_b = run_query(cfg_b, sql_b)
            progress("数据源 B 返回 %d 行" % len(rows_b))
            return cols_a, rows_a, cols_b, rows_b

        self._worker = FunctionWorker(job, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_query_done)
        self._worker.failed.connect(self._on_query_failed)
        self._worker.start()

    def _on_progress(self, text: str):
        self.run_status.setText(text)

    def _on_query_done(self, payload):
        """查询成功（主线程）：缓存结果、构建字段过滤、执行对比。"""
        self._data = payload
        self._stale = False
        cols_a, _rows_a, cols_b, _rows_b = payload
        try:
            key = resolve_compare_key(cols_a, cols_b, self.key_edit.text().strip())
        except Exception as exc:
            self._set_running(False, "对比失败")
            self._error(str(exc))
            return
        # 字段复选框 = 两侧结果列的并集（保持 A 的列顺序），去掉 key
        fields = [c for c in dict.fromkeys(list(cols_a) + list(cols_b)) if c != key]
        self._rebuild_checkboxes(fields)
        self._set_running(False, "查询完成，正在对比…")
        self._recompute()

    def _on_query_failed(self, err: str):
        self._set_running(False, "查询失败")
        self._error("查询执行失败：\n%s" % err)

    def _set_running(self, running: bool, message: str = ""):
        self.btn_compare.setEnabled(not running)
        self.progress.setVisible(running)
        if message:
            self.run_status.setText(message)
            self.run_status.setStyleSheet("color: gray;")

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    # ───────────────────────── 字段过滤 ─────────────────────────

    def _rebuild_checkboxes(self, fields: Sequence[str]):
        """根据查询结果列重建复选框，并应用「固定过滤」。"""
        self._suppress_filter_events = True
        try:
            while self.filter_grid.count():
                item = self.filter_grid.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            self._checkboxes.clear()
            pinned = set(self._pinned_filters)
            per_row = 4
            for i, f in enumerate(fields):
                cb = QCheckBox(f)
                cb.setChecked(f not in pinned)
                cb.toggled.connect(self._on_filter_toggled)
                self.filter_grid.addWidget(cb, i // per_row, i % per_row)
                self._checkboxes[f] = cb
        finally:
            self._suppress_filter_events = False

    def _on_filter_toggled(self, _checked: bool):
        if self._suppress_filter_events:
            return
        self._recompute()  # 临时过滤：立即对缓存结果重新对比

    def _set_all_filters(self, checked: bool):
        self._suppress_filter_events = True
        try:
            for cb in self._checkboxes.values():
                cb.setChecked(checked)
        finally:
            self._suppress_filter_events = False
        self._recompute()

    def _excluded_fields(self) -> List[str]:
        return [f for f, cb in self._checkboxes.items() if not cb.isChecked()]

    def pin_filters(self):
        """把当前未勾选的字段固定到配置文件。"""
        if not self._checkboxes:
            self._warn("请先执行一次对比，生成字段列表后再固定")
            return
        self._pinned_filters = self._excluded_fields()
        if self.save_config(show_message=False):
            self._info(
                "已固定 %d 个过滤字段并保存配置：\n%s"
                % (len(self._pinned_filters), self.config_path_edit.text().strip())
            )

    # ───────────────────────── 对比与渲染 ─────────────────────────

    def _recompute(self):
        if not self._data:
            return
        cols_a, rows_a, cols_b, rows_b = self._data
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._result = compare_results(
                cols_a,
                rows_a,
                cols_b,
                rows_b,
                self.key_edit.text().strip(),
                self._excluded_fields(),
            )
        except Exception as exc:
            self._error("对比失败：\n%s" % exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
        if self._stale:
            # 对比后又改过 SQL/连接:明确提示结果过期
            self.run_status.setText("输入已修改，以下结果可能过期，请重新点击「开始对比」")
            self.run_status.setStyleSheet("color: #b26a00;")
        else:
            suffix = ""
            if self._result.warnings:
                suffix = "（" + "；".join(self._result.warnings) + "）"
            self.run_status.setText("对比完成 " + suffix)
            self.run_status.setStyleSheet("color: gray;")
        self.run_status.setToolTip("\n".join(self._result.warnings))
        self._render_result()

    def _mark_results_stale(self, *_):
        """SQL/连接信息被修改:标记结果过期(改 key 不算,会自动重算)。"""
        if self._result is None:
            return
        self._stale = True
        self.run_status.setText("输入已修改，以下结果可能过期，请重新点击「开始对比」")
        self.run_status.setStyleSheet("color: #b26a00;")
        self._render_diff_overview(self._result)  # 结论区顶部同步过期提示

    def _on_key_changed(self):
        """key 字段修改后立即用缓存数据重新对比(无需重新查询数据库)。"""
        if self._data is not None:
            self._recompute()

    def _clear_results(self):
        """开始新查询前清空旧结果展示。"""
        self._result = None
        self.table.setRowCount(0)
        self.result_count.setText("")
        self.diff_text.clear()
        self.diff_group.setVisible(False)
        for key, lab in self.stat_labels.items():
            lab.setText("%s: -" % self._stat_names[key])

    def _set_stat(self, key: str, label: str, value: int):
        self.stat_labels[key].setText("%s: <b>%d</b>" % (label, value))

    def _render_result(self):
        res = self._result
        if res is None:
            return
        s = res.stats
        self._set_stat("a_rows", "A 行数", s.a_rows)
        self._set_stat("b_rows", "B 行数", s.b_rows)
        self._set_stat("common", "共同 key", s.common_keys)
        self._set_stat("only_a", "仅 A", s.only_a_keys)
        self._set_stat("only_b", "仅 B", s.only_b_keys)
        self._set_stat("diff", "有差异 key", s.diff_keys)
        self._set_stat("same", "完全一致 key", s.same_keys)

        self._render_diff_overview(res)

        _text, keep = FILTER_OPTIONS[self.result_filter.currentIndex()]
        rows = res.rows if keep is None else [r for r in res.rows if r.status in keep]
        total = len(rows)
        shown = rows[:MAX_DISPLAY_ROWS]

        self.table.setRowCount(len(shown))
        for i, r in enumerate(shown):
            values = (
                display_text(r.key),
                r.field,
                display_text(r.a_value),
                display_text(r.b_value),
                STATUS_TEXT[r.status],
            )
            raw_values = (r.key, r.field, r.a_value, r.b_value, STATUS_TEXT[r.status])
            for j, text in enumerate(values):
                item = QTableWidgetItem(text)
                # 完整值存进 UserRole，复制时取它（显示文本被截断不影响复制）
                item.setData(Qt.UserRole, full_text(raw_values[j]))
                self._style_item(item, r.status, j)
                item.setToolTip(full_text(raw_values[j]))
                self.table.setItem(i, j, item)

        if total > len(shown):
            self.result_count.setText(
                "共 %d 条记录，仅显示前 %d 条" % (total, len(shown))
            )
        else:
            self.result_count.setText("共 %d 条记录" % total)

    # ───────────────────────── 对比结论 ─────────────────────────

    def _render_diff_overview(self, res: CompareResult):
        """只输出三项:值不一致 key 数量、具体 key 列表、完全一致 key 数量。

        统计口径 = 参与对比的字段:被过滤(未勾选)字段上的差异不参与统计,
        即只差在被过滤字段的 key 会计入「完全一致」。
        """
        # 每个差异 key 各有多少个 value 不同(res.rows 已只含参与对比字段的差异)
        diff_count: Dict[object, int] = {}
        for r in res.rows:
            if r.status == STATUS_DIFF:
                diff_count[r.key] = diff_count.get(r.key, 0) + 1

        shown_items = list(diff_count.items())[:500]
        detail = json.dumps({full_text(k): c for k, c in shown_items},
                            ensure_ascii=False)
        if len(diff_count) > 500:
            detail += " …(共 %d 个 key)" % len(diff_count)

        lines: List[str] = []
        if self._stale:
            lines.append("⚠ 输入已修改，以下结果可能过期，请重新点击「开始对比」\n")
        # 参与对比字段口径(让过滤效果可见)
        excluded = self._excluded_fields()
        if not res.fields:
            lines.append("⚠ 没有参与对比的字段（所有字段均被过滤），请至少勾选一个字段")
        elif excluded:
            lines.append("参与对比的字段: %d 个（已过滤: %s）"
                         % (len(res.fields), ", ".join(excluded)))
        else:
            lines.append("参与对比的字段: %d 个（全部）" % len(res.fields))
        lines.append("值不一致的 key 数量: %d（共 %d 个 value 不同）"
                     % (len(diff_count), sum(diff_count.values())))
        lines.append("各 key 不同的 value 数: %s" % detail)
        lines.append("完全一致的 key 数量: %d" % res.stats.same_keys)
        self.diff_text.setPlainText("\n".join(lines))
        self.diff_group.setVisible(True)

    # ───────────────────────── 结果选中复制 ─────────────────────────

    def _setup_table_copy(self):
        """Ctrl/Cmd+C 复制 + 右键菜单复制。复制为制表符分隔文本，可直接粘到 Excel。"""
        QShortcut(QKeySequence.Copy, self.table, activated=self.copy_selection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)

    def _table_context_menu(self, pos):
        menu = QMenu(self)
        act_copy = menu.addAction("复制选中内容 (Ctrl+C)")
        act_copy.setEnabled(bool(self.table.selectionModel().selectedIndexes()))
        act_copy.triggered.connect(self.copy_selection)
        act_all = menu.addAction("复制全部结果 (含表头)")
        act_all.setEnabled(self.table.rowCount() > 0)
        act_all.triggered.connect(self.copy_all)
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def copy_selection(self) -> str:
        """复制选中的单元格区域（保持行列位置，制表符分隔）。"""
        selection = self.table.selectionModel().selectedIndexes()
        if not selection:
            return ""
        grid: Dict[int, Dict[int, str]] = {}
        for idx in selection:
            # 优先取 UserRole 中的完整值（显示文本可能被截断）
            value = idx.data(Qt.UserRole)
            if value is None:
                value = idx.data() or ""
            grid.setdefault(idx.row(), {})[idx.column()] = value
        lines = [
            "\t".join(cols[c] for c in sorted(cols))
            for _r, cols in sorted(grid.items())
        ]
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self._flash_copied(len(lines))
        return text

    def copy_all(self) -> str:
        """复制当前表格全部内容（含表头）。"""
        header = [
            self.table.horizontalHeaderItem(c).text()
            for c in range(self.table.columnCount())
        ]
        lines = ["\t".join(header)]
        for r in range(self.table.rowCount()):
            row_values = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if item is None:
                    row_values.append("")
                else:
                    value = item.data(Qt.UserRole)  # 完整值，未截断
                    row_values.append(value if value is not None else item.text())
            lines.append("\t".join(row_values))
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self._flash_copied(len(lines) - 1)
        return text

    def _flash_copied(self, rows: int):
        QToolTip.showText(QCursor.pos(), "已复制 %d 行，可直接粘贴到 Excel" % rows, self.table)

    @staticmethod
    def _style_item(item: QTableWidgetItem, status: str, column: int):
        """结果表格着色：差异值红底粗体直接盯住，完全一致不染色，减少视觉噪音。"""
        font = item.font()
        if status == STATUS_DIFF:
            if column in (2, 3):      # A 值 / B 值：浅红底 + 深红粗体
                item.setBackground(DIFF_VALUE_BG)
                item.setForeground(DIFF_VALUE_FG)
                font.setBold(True)
            elif column == 0:         # 差异 key 加粗
                font.setBold(True)
        elif status in (STATUS_ONLY_A, STATUS_ONLY_B):
            if column == 0:           # 仅单侧存在：key 单元格浅底提示
                item.setBackground(ONLY_KEY_BG[status])
                font.setBold(True)
        if column == 4:               # 状态列：彩色粗体文字（不染底色）
            item.setForeground(STATUS_FG[status])
            font.setBold(True)
        item.setFont(font)

    # ───────────────────────── 关闭处理 ─────────────────────────

    def prepare_for_close(self) -> Optional[FunctionWorker]:
        """关闭前调用：仍在运行的 worker 脱离本 tab，后台跑完自动销毁。"""
        self._closing = True
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.blockSignals(True)
            worker.setParent(None)
            worker.finished.connect(worker.deleteLater)
        self._worker = None
        return worker

    # ───────────────────────── 弹窗工具 ─────────────────────────

    def _info(self, text: str):
        QMessageBox.information(self, "提示", text)

    def _warn(self, text: str):
        QMessageBox.warning(self, "提示", text)

    def _error(self, text: str):
        QMessageBox.critical(self, "错误", text)
