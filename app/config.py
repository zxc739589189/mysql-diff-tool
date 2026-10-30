"""配置模型与 JSON 配置文件读写。

单个 tab 的配置文件格式::

    {
      "task_name": "订单对比",
      "source_a": {"host": "...", "port": 3306, "user": "...", "password": "...", "database": "..."},
      "source_b": {"host": "...", "port": 3306, "user": "...", "password": "...", "database": "..."},
      "sql_a": "SELECT id, name FROM t WHERE env = 'A'",
      "sql_b": "SELECT id, name FROM t WHERE env = 'B'",
      "key_field": "id",
      "fixed_filters": ["update_time"]
    }

「保存全部 tab」的文件格式::

    {"version": 1, "tabs": [<上面的单 tab 配置>, ...]}
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import List

CONFIG_VERSION = 1
DEFAULT_PORT = 3306


def app_base_dir() -> str:
    """程序基准目录：打包后为 exe/app 所在目录，源码运行时为项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_config_dir() -> str:
    """配置文件的固定默认目录（程序目录下的 configs/）。"""
    path = os.path.join(app_base_dir(), "configs")
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class DataSourceConfig:
    """一个 MySQL 数据源的连接信息。"""

    host: str = ""
    port: int = DEFAULT_PORT
    user: str = ""
    password: str = ""
    database: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DataSourceConfig":
        data = data or {}
        try:
            port = int(data.get("port") or DEFAULT_PORT)
        except (TypeError, ValueError):
            port = DEFAULT_PORT
        return cls(
            host=str(data.get("host", "")),
            port=port,
            user=str(data.get("user", "")),
            password=str(data.get("password", "")),
            database=str(data.get("database", "")),
        )


@dataclass
class TabConfig:
    """一个标签页的完整配置。"""

    task_name: str = ""
    source_a: DataSourceConfig = field(default_factory=DataSourceConfig)
    source_b: DataSourceConfig = field(default_factory=DataSourceConfig)
    sql_a: str = ""
    sql_b: str = ""
    key_field: str = ""                # 留空 = 默认结果第一列
    fixed_filters: List[str] = field(default_factory=list)  # 固定过滤字段（不参与对比）

    def to_dict(self) -> dict:
        return {
            "task_name": self.task_name,
            "source_a": self.source_a.to_dict(),
            "source_b": self.source_b.to_dict(),
            "sql_a": self.sql_a,
            "sql_b": self.sql_b,
            "key_field": self.key_field,
            "fixed_filters": list(self.fixed_filters),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TabConfig":
        data = data or {}
        return cls(
            task_name=str(data.get("task_name", "")),
            source_a=DataSourceConfig.from_dict(data.get("source_a")),
            source_b=DataSourceConfig.from_dict(data.get("source_b")),
            sql_a=str(data.get("sql_a", "")),
            sql_b=str(data.get("sql_b", "")),
            key_field=str(data.get("key_field", "")),
            fixed_filters=[str(x) for x in (data.get("fixed_filters") or [])],
        )


def load_tab_config(path: str) -> TabConfig:
    """从 JSON 文件读取单个 tab 的配置。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("配置文件内容必须是 JSON 对象")
    return TabConfig.from_dict(data)


def save_tab_config(path: str, config: TabConfig) -> None:
    """把单个 tab 的配置写入 JSON 文件。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)


def save_all_configs(path: str, configs: List[TabConfig]) -> None:
    """保存全部 tab 配置到一个 JSON 文件。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    payload = {
        "version": CONFIG_VERSION,
        "tabs": [c.to_dict() for c in configs],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_all_configs(path: str) -> List[TabConfig]:
    """从 JSON 文件加载全部 tab 配置。

    兼容两种格式：{"tabs": [...]} 或直接是配置数组 [...]。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "tabs" in data:
        tabs = data["tabs"]
    elif isinstance(data, list):
        tabs = data
    else:
        raise ValueError("全部配置文件格式不正确：需要 {\"tabs\": [...]} 或配置数组")
    return [TabConfig.from_dict(t) for t in tabs]
