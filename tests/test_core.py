"""核心逻辑（对比 + 配置）离线测试：python3 tests/test_core.py"""
import json
import os
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.compare import (  # noqa: E402
    STATUS_DIFF, STATUS_ONLY_A, STATUS_ONLY_B, STATUS_SAME,
    compare_results, resolve_key_field,
)
from app.config import (  # noqa: E402
    DataSourceConfig, TabConfig,
    load_all_configs, load_tab_config, save_all_configs, save_tab_config,
)

failures = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond:
        failures.append(name)


# ── 对齐 key 解析 ──
check("key 留空取第一列", resolve_key_field(["id", "name"], "") == "id")
check("指定 key", resolve_key_field(["id", "name"], "name") == "name")
try:
    resolve_key_field(["id"], "xx")
    check("非法 key 报错", False)
except ValueError:
    check("非法 key 报错", True)

# ── 基础对比 ──
cols = ["id", "name", "price"]
ra = [(1, "a", 10), (2, "b", 20), (3, "c", 30)]
rb = [(1, "a", 10), (2, "b", 21), (4, "d", 40)]
res = compare_results(cols, ra, cols, rb, "id", [])
s = res.stats
check("A 行数", s.a_rows == 3)
check("B 行数", s.b_rows == 3)
check("共同 key", s.common_keys == 2)
check("仅 A", s.only_a_keys == 1)
check("仅 B", s.only_b_keys == 1)
check("有差异 key", s.diff_keys == 1)
check("完全一致 key", s.same_keys == 1)
statuses = [r.status for r in res.rows]
check("结果行数 = 共同key*字段数 + 仅A + 仅B", len(res.rows) == 2 * 2 + 1 + 1)
check("包含四种状态中的三类",
      STATUS_DIFF in statuses and STATUS_ONLY_A in statuses and STATUS_ONLY_B in statuses)
diff_rows = [r for r in res.rows if r.status == STATUS_DIFF]
check("差异行是 key=2 的 price 字段",
      len(diff_rows) == 1 and diff_rows[0].key == 2 and diff_rows[0].field == "price")

# ── 字段过滤 ──
res2 = compare_results(cols, ra, cols, rb, "id", ["price"])
check("过滤掉 price 后无差异", res2.stats.diff_keys == 0 and res2.stats.same_keys == 2)
check("参与字段只剩 name", res2.fields == ["name"])

# ── 数字容差（Decimal vs int）──
ra3 = [(1, Decimal("1.0"))]
rb3 = [(1, 1)]
res3 = compare_results(["id", "v"], ra3, ["id", "v"], rb3, "id", [])
check("Decimal('1.0') 与 1 视为一致", res3.stats.same_keys == 1)

# ── None 比较 ──
ra4 = [(1, None)]
rb4 = [(1, None)]
rb5 = [(1, "x")]
check("None==None 一致", compare_results(["id", "v"], ra4, ["id", "v"], rb4, "id", []).stats.same_keys == 1)
check("None vs 值 不一致", compare_results(["id", "v"], ra4, ["id", "v"], rb5, "id", []).stats.diff_keys == 1)

# ── 重复 key 警告 ──
res6 = compare_results(cols, [(1, "a", 1), (1, "a", 2)], cols, [(1, "a", 1)], "id", [])
check("重复 key 产生警告", len(res6.warnings) == 1 and "重复" in res6.warnings[0])

# ── 列不一致警告 ──
res7 = compare_results(["id", "a_col"], [(1, 2)], ["id", "b_col"], [(1, 2)], "id", [])
check("仅单侧存在的列产生警告", len(res7.warnings) == 2)

# ── 配置读写 ──
tmp = tempfile.mkdtemp()
cfg = TabConfig(
    task_name="测试任务",
    source_a=DataSourceConfig(host="h1", port=3307, user="u", password="p", database="d"),
    source_b=DataSourceConfig(host="h2"),
    sql_a="select 1",
    sql_b="select 2",
    key_field="id",
    fixed_filters=["f1", "f2"],
)
p1 = os.path.join(tmp, "tab.json")
save_tab_config(p1, cfg)
check("单配置读写一致", load_tab_config(p1) == cfg)

p2 = os.path.join(tmp, "all.json")
save_all_configs(p2, [cfg, cfg])
loaded = load_all_configs(p2)
check("全部配置读写", len(loaded) == 2 and loaded[0] == cfg)

# 容错：缺字段 / 端口字符串
raw = json.loads('{"task_name":"x","source_a":{"host":"h","port":"3308"}}')
cfg2 = TabConfig.from_dict(raw)
check("端口字符串转 int", cfg2.source_a.port == 3308)
check("缺省字段默认", cfg2.key_field == "" and cfg2.fixed_filters == [])

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("ALL CORE TESTS PASSED")
