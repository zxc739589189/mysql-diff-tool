"""MySQL 查询封装（基于 pymysql）。

本模块只做纯 IO，不涉及任何 Qt / 界面代码，方便在后台线程中调用。
"""
from __future__ import annotations

from typing import List, Tuple

import pymysql

from .config import DataSourceConfig

CONNECT_TIMEOUT = 10      # 连接超时（秒）
READ_TIMEOUT = 300        # 读取超时（秒）


def _connect(cfg: DataSourceConfig) -> pymysql.connections.Connection:
    if not cfg.host:
        raise ValueError("数据库主机(host)不能为空")
    return pymysql.connect(
        host=cfg.host,
        port=int(cfg.port or DataSourceConfig.port),
        user=cfg.user,
        password=cfg.password,
        database=cfg.database or None,
        charset="utf8mb4",
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
        autocommit=True,
    )


def test_connection(cfg: DataSourceConfig) -> str:
    """测试连接，成功时返回描述文本，失败抛异常。"""
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            row = cur.fetchone()
        return "连接成功，MySQL 版本: %s" % (row[0] if row else "未知")
    finally:
        conn.close()


def run_query(cfg: DataSourceConfig, sql: str) -> Tuple[List[str], List[tuple]]:
    """执行查询，返回 (列名列表, 行数据列表)。"""
    if not sql or not sql.strip():
        raise ValueError("SQL 语句不能为空")
    conn = _connect(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            if cur.description is None:
                raise ValueError("SQL 没有返回结果集（需要 SELECT 查询）")
            columns = [d[0] for d in cur.description]
            rows = list(cur.fetchall())
        return columns, rows
    finally:
        conn.close()
