"""结果集对齐与逐字段对比的核心逻辑（纯 Python，不依赖 Qt）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

# 四种对比状态
STATUS_DIFF = "diff"        # 值不一致
STATUS_ONLY_A = "only_a"    # 仅 A 存在
STATUS_ONLY_B = "only_b"    # 仅 B 存在
STATUS_SAME = "same"        # 完全一致

STATUS_TEXT = {
    STATUS_DIFF: "值不一致",
    STATUS_ONLY_A: "仅 A 存在",
    STATUS_ONLY_B: "仅 B 存在",
    STATUS_SAME: "完全一致",
}

WHOLE_ROW = "(整行)"

# 特殊 key:按行号对齐（不依赖任何 key 列，第 1 行对第 1 行）
ROW_NUMBER_KEY = "(行号)"
# 兼容中文输入法全角括号
_ROW_NUMBER_ALIASES = {ROW_NUMBER_KEY, "行号", "（行号）"}


@dataclass
class DiffRow:
    """结果表格中的一行。"""

    key: object
    field: str
    a_value: object
    b_value: object
    status: str


@dataclass
class CompareStats:
    a_rows: int = 0        # A 结果行数
    b_rows: int = 0        # B 结果行数
    common_keys: int = 0   # 两侧都存在的 key 数
    only_a_keys: int = 0   # 仅 A 存在的 key 数
    only_b_keys: int = 0   # 仅 B 存在的 key 数
    diff_keys: int = 0     # 共同 key 中有字段差异的 key 数
    same_keys: int = 0     # 共同 key 中完全一致的 key 数


@dataclass
class CompareResult:
    key_field: str
    fields: List[str]                 # 实际参与对比的字段
    rows: List[DiffRow] = field(default_factory=list)
    stats: CompareStats = field(default_factory=CompareStats)
    warnings: List[str] = field(default_factory=list)


def resolve_key_field(columns: Sequence[str], key_field: str) -> str:
    """确定对齐 key：用户未指定时取结果第一列。"""
    if not columns:
        raise ValueError("查询结果没有任何列")
    key_field = (key_field or "").strip()
    if key_field:
        if key_field not in columns:
            raise ValueError(
                "对齐 key 字段 “%s” 不在查询结果列中，可选列: %s"
                % (key_field, ", ".join(columns))
            )
        return key_field
    return columns[0]


def _values_equal(a: object, b: object) -> bool:
    """判断两个值是否一致，对数字做类型容差（如 Decimal('1.0') 与 1）。"""
    if a is None or b is None:
        return a is None and b is None
    if a == b:
        return True
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except Exception:
            return False
    return False


def _index_rows(
    columns: Sequence[str], rows: Sequence[tuple], key_field: str
) -> Tuple["Dict[object, tuple]", List[object], int]:
    """按 key 建索引，返回 (key->行, key 顺序, 重复 key 数)。重复 key 保留首行。"""
    key_idx = columns.index(key_field)
    mapping: Dict[object, tuple] = {}
    order: List[object] = []
    duplicates = 0
    for row in rows:
        k = row[key_idx]
        if k in mapping:
            duplicates += 1
            continue
        mapping[k] = row
        order.append(k)
    return mapping, order, duplicates


def resolve_compare_key(
    cols_a: Sequence[str], cols_b: Sequence[str], key_field: str
) -> str:
    """确定对齐 key。

    - 填 ``(行号)``（或 ``行号``）: 按行顺序对齐，不需要任何 key 列；
    - 留空: 取 A 结果第一列；
    - 否则校验该列在两侧结果中都存在。
    """
    if (key_field or "").strip() in _ROW_NUMBER_ALIASES:
        return ROW_NUMBER_KEY
    key = resolve_key_field(cols_a, key_field)
    if key not in cols_b:
        raise ValueError(
            "对齐 key 字段 “%s” 不在数据源 B 的查询结果列中，可选列: %s"
            % (key, ", ".join(cols_b))
        )
    return key


def _row_digest(fields: Sequence[str], idxs: Sequence[int], row: tuple) -> str:
    """整行摘要（只含参与对比的字段，完整不截断），用于「仅 A/B 存在」的展示。"""
    if not fields:
        return "(所有字段均被过滤)"
    parts = []
    for f, i in zip(fields, idxs):
        v = row[i]
        parts.append("%s=%s" % (f, "NULL" if v is None else v))
    return ", ".join(parts)


def compare_results(
    cols_a: Sequence[str],
    rows_a: Sequence[tuple],
    cols_b: Sequence[str],
    rows_b: Sequence[tuple],
    key_field: str = "",
    excluded_fields: Optional[Sequence[str]] = None,
) -> CompareResult:
    """按 key 对齐两组结果集并逐字段对比。

    - 参与对比的字段 = 两侧结果都存在的列（保持 A 的列顺序），排除 key 与被过滤字段。
    - 共同 key：每个参与字段产生一行结果（值不一致 / 完全一致）。
    - 仅一侧存在的 key：产生一行「(整行)」摘要记录。
    """
    excluded = set(excluded_fields or [])
    key = resolve_compare_key(cols_a, cols_b, key_field)
    row_number_mode = key == ROW_NUMBER_KEY

    common_cols = [c for c in cols_a if c in cols_b and c != key and c not in excluded]
    idx_a = [cols_a.index(c) for c in common_cols]
    idx_b = [cols_b.index(c) for c in common_cols]

    if row_number_mode:
        # 按行号对齐:第 1 行对第 1 行,多出的行算「仅 A/B 存在」
        order_a = list(range(1, len(rows_a) + 1))
        order_b = list(range(1, len(rows_b) + 1))
        map_a = dict(zip(order_a, rows_a))
        map_b = dict(zip(order_b, rows_b))
        dup_a = dup_b = 0
    else:
        map_a, order_a, dup_a = _index_rows(cols_a, rows_a, key)
        map_b, order_b, dup_b = _index_rows(cols_b, rows_b, key)

    result = CompareResult(key_field=key, fields=list(common_cols))
    stats = result.stats
    stats.a_rows = len(rows_a)
    stats.b_rows = len(rows_b)

    if dup_a:
        result.warnings.append("数据源 A 存在 %d 个重复 key（按首行参与对比）" % dup_a)
    if dup_b:
        result.warnings.append("数据源 B 存在 %d 个重复 key（按首行参与对比）" % dup_b)
    only_in_a_cols = [c for c in cols_a if c not in cols_b and c != key]
    only_in_b_cols = [c for c in cols_b if c not in cols_a and c != key]
    if only_in_a_cols:
        result.warnings.append("字段 %s 仅存在于 A 的结果列，未参与对比" % ", ".join(only_in_a_cols))
    if only_in_b_cols:
        result.warnings.append("字段 %s 仅存在于 B 的结果列，未参与对比" % ", ".join(only_in_b_cols))

    keys_a = set(map_a)
    keys_b = set(map_b)
    common_keys = [k for k in order_a if k in keys_b]
    only_a_keys = [k for k in order_a if k not in keys_b]
    only_b_keys = [k for k in order_b if k not in keys_a]

    stats.common_keys = len(common_keys)
    stats.only_a_keys = len(only_a_keys)
    stats.only_b_keys = len(only_b_keys)

    for k in common_keys:
        ra, rb = map_a[k], map_b[k]
        key_has_diff = False
        for c, ia, ib in zip(common_cols, idx_a, idx_b):
            va, vb = ra[ia], rb[ib]
            if _values_equal(va, vb):
                status = STATUS_SAME
            else:
                status = STATUS_DIFF
                key_has_diff = True
            result.rows.append(DiffRow(k, c, va, vb, status))
        if key_has_diff:
            stats.diff_keys += 1
        else:
            stats.same_keys += 1

    for k in only_a_keys:
        result.rows.append(
            DiffRow(k, WHOLE_ROW, _row_digest(common_cols, idx_a, map_a[k]), "—", STATUS_ONLY_A)
        )
    for k in only_b_keys:
        result.rows.append(
            DiffRow(k, WHOLE_ROW, "—", _row_digest(common_cols, idx_b, map_b[k]), STATUS_ONLY_B)
        )

    return result
