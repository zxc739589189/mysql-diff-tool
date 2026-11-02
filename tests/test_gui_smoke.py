"""GUI 冒烟测试（离屏模式，不需要显示器/MySQL）：

    QT_QPA_PLATFORM=offscreen .venv/bin/python tests/test_gui_smoke.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

# 离屏模式下避免模态弹窗阻塞测试
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)

from app.compare import STATUS_DIFF, STATUS_ONLY_A, STATUS_ONLY_B  # noqa: E402
from app.config import load_all_configs  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

failures = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond:
        failures.append(name)


app = QApplication([])
win = MainWindow()
check("启动后默认 1 个标签页", win.tabs.count() == 1)

# ── 多标签页：新建 / 重命名 / 标题同步 ──
tab1 = win.tabs.currentWidget()
tab2 = win.new_tab()
check("新建标签页", win.tabs.count() == 2 and win.tabs.currentWidget() is tab2)
tab2.set_task_name("订单对比")
check("任务名同步到 tab 标题", win.tabs.tabText(win.tabs.indexOf(tab2)) == "订单对比")
check("配置路径自动跟随任务名", tab1.config_path_edit.text().endswith("任务 1.json"))

# ── 模拟查询结果（跳过真实数据库，直接喂数据）──
cols = ["id", "name", "price"]
ra = [(1, "a", 10), (2, "b", 20), (3, "c", 30)]
rb = [(1, "a", 10), (2, "b", 21), (4, "d", 40)]
tab2._on_query_done((cols, ra, cols, rb))

check("生成了 2 个字段复选框（去掉 key）", len(tab2._checkboxes) == 2)
check("字段默认全部勾选", all(cb.isChecked() for cb in tab2._checkboxes.values()))
check("统计 A 行数", "3" in tab2.stat_labels["a_rows"].text())
check("统计仅 A", "1" in tab2.stat_labels["only_a"].text())
check("默认过滤「仅看差异」显示 3 行", tab2.table.rowCount() == 3)

statuses = {tab2.table.item(i, 4).text() for i in range(tab2.table.rowCount())}
check("差异行含三类状态", statuses == {"值不一致", "仅 A 存在", "仅 B 存在"})

tab2.result_filter.setCurrentIndex(0)  # 全部
check("「全部」显示 6 行", tab2.table.rowCount() == 6)

# ── 结果选中复制 ──
tab2.table.selectAll()
copied = tab2.copy_selection()
check("Ctrl+C 复制选中区域（6 行、制表符分隔）",
      copied.count("\n") == 5 and copied.count("\t") == 6 * 4)
tab2.table.clearSelection()
tab2.table.setCurrentCell(0, 2)  # 等效于点击选中该单元格
copied_cell = tab2.copy_selection()
check("复制单个单元格", copied_cell == "a")
all_text = tab2.copy_all()
check("复制全部含表头",
      all_text.split("\n")[0] == "Key\t字段名\tA 值\tB 值\t状态"
      and len(all_text.split("\n")) == 7)

# ── 临时字段过滤：取消 price 勾选 → 差异消失 ──
tab2.result_filter.setCurrentIndex(1)  # 切回「仅看差异」
tab2._checkboxes["price"].setChecked(False)
check("取消 price 勾选后仅看差异为 2 行（仅A/仅B）", tab2.table.rowCount() == 2)
check("取消 price 后无差异 key", tab2._result.stats.diff_keys == 0)
tab2._checkboxes["price"].setChecked(True)

# ── 固定到配置 + 保存 / 读取 ──
tmp = tempfile.mkdtemp()
cfg_path = os.path.join(tmp, "订单对比.json")
tab2.config_path_edit.setText(cfg_path)
tab2._checkboxes["price"].setChecked(False)
tab2.pin_filters()  # 固定 price 并保存
check("固定过滤写入配置", '"price"' in open(cfg_path, encoding="utf-8").read())
tab2._checkboxes["price"].setChecked(True)
tab2._pinned_filters = []
tab2.load_config()  # 读取配置
check("读取配置恢复固定过滤", tab2._pinned_filters == ["price"])

tab2._on_query_done((cols, ra, cols, rb))  # 重新对比 → price 应被自动过滤
check("重新对比时 price 自动取消勾选", not tab2._checkboxes["price"].isChecked())
check("固定过滤生效（无差异 key）", tab2._result.stats.diff_keys == 0)

# ── 长值不截断（显示与复制都是完整值）──
long_val = "v" * 500
tab2._on_query_done((["id", "v"], [(1, long_val)], ["id", "v"], [(1, long_val + "y")]))
tab2.result_filter.setCurrentIndex(0)
check("显示不截断", tab2.table.item(0, 2).text() == long_val)
tab2.table.selectAll()
copied_long = tab2.copy_selection()
check("复制为完整值不截断", long_val in copied_long and "…" not in copied_long)
# 「仅 A 存在」整行摘要也不截断
tab2._on_query_done((["id", "v"], [(9, long_val)], ["id", "v"], [(1, "x")]))
tab2.result_filter.setCurrentIndex(3)  # 仅 A 存在
tab2.table.selectAll()
copied_digest = tab2.copy_selection()
check("整行摘要不截断", long_val in copied_digest)

# ── 对比结论模块(不一致 key 数量 + 列表 + 一致数量)──
tab2._on_query_done((cols, ra, cols, rb))  # 恢复 3 产品数据集
tab2._checkboxes["price"].setChecked(True)  # 固定过滤使 price 默认不勾,先勾上
conclusion = tab2.diff_text.toPlainText()
check("结论:不一致字段数量", "值不一致的字段数量: 1" in conclusion)
check("结论:不一致字段列表", '值不一致的字段: ["price"]' in conclusion)
check("结论:一致字段数量", "完全一致的字段数量: 1" in conclusion)  # name 一致
tab2._checkboxes["price"].setChecked(False)  # 过滤 price → 其差异不参与统计
conclusion2 = tab2.diff_text.toPlainText()
check("被过滤字段不计入不一致字段",
      "值不一致的字段数量: 0" in conclusion2
      and '值不一致的字段: []' in conclusion2)
check("过滤后只剩 name 参与且一致", "完全一致的字段数量: 1" in conclusion2)
tab2._checkboxes["price"].setChecked(True)

# ── key 修改即时重算 + 结果过期提示 ──
tab2.key_edit.setText("(行号)")
tab2._on_key_changed()
check("key 改为(行号)立即重算",
      tab2._result.key_field == "(行号)" and tab2._result.stats.diff_keys == 2)
tab2.key_edit.setText("(行号)")  # 全角括号同样生效
tab2._on_key_changed()
check("全角(行号)立即重算", tab2._result.key_field == "(行号)")
# 共同 key 为 0 时必须警告"没有配对对比",且一致字段不得虚报
tab2._on_query_done((cols, [(1, "a", 10)], cols, [(4, "d", 40)]))
tab2.key_edit.setText("id")
tab2._on_key_changed()
warn_text = tab2.diff_text.toPlainText()
check("key 对不上时明确警告未对比",
      "共同 key 为 0" in warn_text and "没有进行 value 对比" in warn_text)
check("未参与对比的字段不计入一致", "完全一致的字段数量: 0" in warn_text)
tab2._on_query_done((cols, ra, cols, rb))  # 恢复数据
tab2.key_edit.setText("")
tab2._on_key_changed()
tab2.sql_a.setPlainText("select 1 -- 修改了 SQL")
check("修改 SQL 后提示结果过期",
      "可能过期" in tab2.run_status.text() and "可能过期" in tab2.diff_text.toPlainText())
tab2._on_query_done((cols, ra, cols, rb))  # 重新查询 → 过期标记清除
check("重新对比后过期提示清除", "可能过期" not in tab2.diff_text.toPlainText())
tab2.key_edit.setText("")

# ── 复制 A 的 SQL 到 B ──
tab2.sql_a.setPlainText("SELECT * FROM t WHERE env='A'")
tab2.btn_copy_ab.click()
check("复制 A 的 SQL 到 B", tab2.sql_b.toPlainText() == "SELECT * FROM t WHERE env='A'")

# ── 保存 / 加载全部 tab 配置 ──
all_path = os.path.join(tmp, "all_tabs.json")
from app.config import save_all_configs  # noqa: E402
save_all_configs(all_path, win._all_tab_configs())
loaded = load_all_configs(all_path)
check("保存全部配置", len(loaded) == 2)
before = win.tabs.count()
for cfg in loaded:
    win.new_tab(cfg)
check("加载全部配置为新 tab", win.tabs.count() == before + 2)

# ── 关闭标签页 ──
win.close_tab(win.tabs.indexOf(tab2))
check("关闭标签页", win.tabs.indexOf(tab2) == -1)

# ── key 字段错误提示 ──
tab1.key_edit.setText("not_exist")
tab1._on_query_done((cols, ra, cols, rb))  # 应弹错误框（离屏模式下模态框需处理）
check("非法 key 不产生结果", tab1._result is None)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("ALL GUI SMOKE TESTS PASSED")
