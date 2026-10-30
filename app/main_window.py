"""主窗口：多标签页管理 + 「保存/加载全部 tab 配置」。"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QToolButton,
)

from .compare_tab import CompareTab
from .config import (
    TabConfig,
    default_config_dir,
    load_all_configs,
    save_all_configs,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MySQL 数据对比工具")
        self._tab_counter = 0

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

        # 右上角「+」新建按钮
        add_btn = QToolButton()
        add_btn.setText("+")
        add_btn.setAutoRaise(True)
        add_btn.setToolTip("新建标签页 (Ctrl+T)")
        add_btn.clicked.connect(lambda: self.new_tab())
        self.tabs.setCornerWidget(add_btn, Qt.TopRightCorner)

        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBarDoubleClicked.connect(self.rename_tab)

        self._build_menus()
        self.new_tab()

    # ───────────────────────── 菜单 ─────────────────────────

    def _build_menus(self):
        m_file = self.menuBar().addMenu("文件(&F)")

        act_new = QAction("新建标签页", self)
        act_new.setShortcut(QKeySequence("Ctrl+T"))
        act_new.triggered.connect(lambda: self.new_tab())
        m_file.addAction(act_new)

        act_rename = QAction("重命名标签页", self)
        act_rename.setShortcut(QKeySequence("F2"))
        act_rename.triggered.connect(lambda: self.rename_tab(self.tabs.currentIndex()))
        m_file.addAction(act_rename)

        act_close = QAction("关闭当前标签页", self)
        act_close.setShortcut(QKeySequence("Ctrl+W"))
        act_close.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        m_file.addAction(act_close)

        m_file.addSeparator()

        act_save_all = QAction("保存全部 tab 配置到文件…", self)
        act_save_all.triggered.connect(self.save_all)
        m_file.addAction(act_save_all)

        act_load_all = QAction("加载全部 tab 配置…", self)
        act_load_all.triggered.connect(self.load_all)
        m_file.addAction(act_load_all)

        m_file.addSeparator()

        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_help = self.menuBar().addMenu("帮助(&H)")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

    def _about(self):
        QMessageBox.about(
            self,
            "关于",
            "MySQL 数据对比工具\n\n"
            "对比两个 MySQL 数据源中同类查询的结果集：\n"
            "按 key 对齐、逐字段比较，区分值不一致 / 仅 A / 仅 B / 完全一致。\n\n"
            "技术栈：PySide6 + PyMySQL",
        )

    # ───────────────────────── 标签页管理 ─────────────────────────

    def new_tab(self, config: Optional[TabConfig] = None) -> CompareTab:
        self._tab_counter += 1
        tab = CompareTab()
        if config is not None:
            tab.set_config(config)
            if not tab.task_name():
                tab.set_task_name("任务 %d" % self._tab_counter)
        else:
            tab.set_task_name("任务 %d" % self._tab_counter)
        title = tab.task_name() or "未命名"
        index = self.tabs.addTab(tab, title)
        tab.title_changed.connect(
            lambda text, t=tab: self._on_tab_title_changed(t, text)
        )
        self.tabs.setCurrentIndex(index)
        return tab

    def _on_tab_title_changed(self, tab: CompareTab, text: str):
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.setTabText(index, text or "未命名")

    def close_tab(self, index: int):
        if index < 0:
            return
        tab = self.tabs.widget(index)
        if not isinstance(tab, CompareTab):
            return
        if tab.is_busy():
            ret = QMessageBox.question(
                self,
                "关闭标签页",
                "「%s」正在执行查询，确定关闭？\n（关闭后查询结果将被丢弃）"
                % self.tabs.tabText(index),
            )
            if ret != QMessageBox.Yes:
                return
        tab.prepare_for_close()
        self.tabs.removeTab(index)
        tab.deleteLater()

    def rename_tab(self, index: int):
        if index < 0:
            return
        tab = self.tabs.widget(index)
        if not isinstance(tab, CompareTab):
            return
        name, ok = QInputDialog.getText(
            self, "重命名标签页", "新名称:", text=self.tabs.tabText(index)
        )
        if ok and name.strip():
            tab.set_task_name(name.strip())  # 任务名与标签页标题保持同步

    # ───────────────────────── 全部配置保存 / 加载 ─────────────────────────

    def _all_tab_configs(self) -> List[TabConfig]:
        configs = []
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, CompareTab):
                configs.append(tab.get_config())
        return configs

    def save_all(self):
        if self.tabs.count() == 0:
            QMessageBox.warning(self, "提示", "当前没有任何标签页")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存全部 tab 配置",
            default_config_dir() + "/all_tabs.json",
            "JSON 配置 (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            save_all_configs(path, self._all_tab_configs())
        except Exception as exc:
            QMessageBox.critical(self, "错误", "保存全部配置失败：\n%s" % exc)
            return
        QMessageBox.information(
            self, "提示", "已保存 %d 个标签页的配置：\n%s" % (self.tabs.count(), path)
        )

    def load_all(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载全部 tab 配置", default_config_dir(), "JSON 配置 (*.json)"
        )
        if not path:
            return
        try:
            configs = load_all_configs(path)
        except Exception as exc:
            QMessageBox.critical(self, "错误", "加载全部配置失败：\n%s" % exc)
            return
        if not configs:
            QMessageBox.warning(self, "提示", "文件中没有可加载的标签页配置")
            return
        for cfg in configs:
            self.new_tab(cfg)
        QMessageBox.information(
            self, "提示", "已加载 %d 个标签页配置" % len(configs)
        )

    # ───────────────────────── 退出处理 ─────────────────────────

    def closeEvent(self, event):
        orphans = []
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, CompareTab):
                worker = tab.prepare_for_close()
                if worker is not None and worker.isRunning():
                    orphans.append(worker)
        # 退出前给仍在运行的查询最多 2 秒收尾，避免后台线程被强杀
        for worker in orphans:
            worker.wait(2000)
        event.accept()
