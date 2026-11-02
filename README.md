# MySQL 数据对比工具（MySQLDiffTool）

一个跨平台桌面工具：对比**两个不同 MySQL 库/实例**中同类查询的结果集，
按对齐 key 逐字段比较，直观展示 **值不一致 / 仅 A 存在 / 仅 B 存在 / 完全一致** 四类结果。

- 技术栈：PySide6（界面）+ PyMySQL（连接 MySQL）
- 多标签页：每个 tab 独立配置、互不影响，可新建 / 关闭 / 重命名
- 配置存 JSON 文件，可一键读取 / 保存，支持批量保存 / 加载全部 tab
- 查询在后台线程执行，不卡界面

## 目录结构

```
mysql-diff-tool/
├── main.py                 # 程序入口
├── app/
│   ├── main_window.py      # 主窗口：tab 管理、保存/加载全部配置
│   ├── compare_tab.py      # 单个对比标签页（界面 + 交互）
│   ├── compare.py          # 对齐 + 逐字段对比核心逻辑（纯 Python）
│   ├── config.py           # 配置模型与 JSON 读写
│   ├── db.py               # pymysql 查询封装
│   └── workers.py          # 后台线程（QThread）
├── configs/
│   └── example.json        # 单 tab 配置文件示例
├── requirements.txt
├── MySQLDiffTool.spec      # PyInstaller 打包配置
├── build_windows.bat       # Windows 一键打包
└── build_macos.sh          # macOS 一键打包
```

## 一、源码运行

要求 Python 3.9+：

```bash
cd mysql-diff-tool
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## 二、使用说明

1. **标签页**：顶部 tab 可新建（右上角 `+` 或 Ctrl+T）、关闭（Ctrl+W）、
   双击或按 F2 重命名；每个 tab 的配置互相独立。
2. **配置文件**：每个 tab 顶部有固定的配置文件路径（默认 `configs/<任务名>.json`，可改）；
   「浏览…」打开文件对话框**直接选择已有配置文件**（不创建新文件），
   点「读取配置」一键载入，点「保存配置」一键写入当前路径。
3. **数据源**：分别填写数据源 A / B 的主机、端口、用户名、密码、数据库名，
   可点「测试连接」验证。
4. **SQL**：A、B 两条 SQL 主体相同、仅 WHERE 条件不同；
   「复制 A 的 SQL 到 B →」可一键复制后再改条件。
5. **对齐 key 字段**：指定用于对齐两组结果集的字段。**留空时自动判断**：
   A、B 各只有 1 行 → **直接逐字段对比这一行，无需任何 key**；
   多行 → 默认取查询结果第一列做 key。填 `(行号)`（全角 `（行号）` 同样识别）
   则强制按行顺序对齐（第 1 行对第 1 行，多出的行记为仅 A/仅 B）。
   key 修改后回车/移开焦点即自动重算（不重查数据库）；
   修改 SQL 或连接信息后，界面会明确提示"结果可能过期"，需重新点击「开始对比」，
   且每次点击开始对比都会先清空旧结果，杜绝过期数字误导。
6. **开始对比**：后台线程分别查询 A、B，完成后自动逐字段对比。
7. **字段过滤**：查询结果的每个字段（除 key）显示为复选框，默认全部勾选参与对比；
   取消勾选立即重新对比（临时过滤，本次有效）；
   点「固定到配置」把当前未勾选字段写入配置文件，下次读取配置自动生效。
8. **结果**：顶部统计 A 行数 / B 行数 / 共同 key / 仅 A / 仅 B / 有差异 key / 完全一致 key；
   表格列为 `Key、字段名、A 值、B 值、状态`。配色低刺激、突出差异（完全一致不染色）：

   | 状态 | 样式 |
   |---|---|
   | 值不一致 | **A 值 / B 值**浅红底 + 深红粗体，key 加粗，一眼盯住差异 |
   | 仅 A 存在 | key 单元格浅黄底 |
   | 仅 B 存在 | key 单元格浅蓝底 |
   | 完全一致 | 不染色，状态列绿色文字 |

   「结果过滤」下拉框可按状态筛选（默认「仅看差异」，直接列出所有不一样的 key）；
   仅一侧存在的 key 以 `(整行)` 摘要展示（摘要只包含勾选参与对比的字段）。
9. **对比结论（独立模块）**：对比出结果后自动出现在字段过滤下方，按**字段口径**输出：

   ```
   值不一致的字段数量: 1
   值不一致的字段: ["product_name"]
   完全一致的字段数量: 2
   ```

   即：参与对比（勾选）的字段里，哪些字段的值在至少一行上不一致（该字段在所有
   行都一致则计入「完全一致」）。文本可直接选中复制；
   看完结论再去下方结果表（「仅看差异」）核对 A/B 具体值。
10. **结果复制**：表格支持拖选 / Shift / Ctrl(Cmd) 多选任意区域，`Ctrl+C`(Mac 为 `Cmd+C`)
   复制选中内容；右键菜单另有「复制选中内容」和「复制全部结果（含表头）」。
   复制结果为制表符分隔文本，可直接粘贴到 Excel / Numbers / 文本编辑器。
   所有值（含「仅 A/仅 B 存在」的整行摘要）**不做任何长度截断**，显示与复制均为数据库原始完整值。
11. **批量配置**：菜单 `文件 → 保存全部 tab 配置到文件… / 加载全部 tab 配置…`。

### 配置文件格式（单个 tab）

```json
{
  "task_name": "订单对比",
  "source_a": {"host": "10.0.0.1", "port": 3306, "user": "readonly", "password": "***", "database": "db1"},
  "source_b": {"host": "10.0.0.2", "port": 3306, "user": "readonly", "password": "***", "database": "db2"},
  "sql_a": "SELECT id, amount, status FROM orders WHERE dt = '2026-10-29'",
  "sql_b": "SELECT id, amount, status FROM orders WHERE dt = '2026-10-30'",
  "key_field": "id",
  "fixed_filters": ["update_time"]
}
```

「全部 tab」文件为 `{"version": 1, "tabs": [ <单 tab 配置>, ... ]}`。
示例见 `configs/example.json`。

> ⚠️ 注意：密码以**明文**保存在 JSON 中，请妥善保管配置文件，不要把真实配置提交到 git。

## 三、打包（用户无需安装 Python）

先安装 PyInstaller：`pip install pyinstaller`（打包脚本会自动装）。

### Windows → 单文件 exe

在 Windows 机器上执行（任选其一）：

```bat
build_windows.bat
```

或手动：

```bat
pyinstaller --noconfirm --clean MySQLDiffTool.spec
```

产物：`dist\MySQLDiffTool.exe`，双击即用，可直接拷贝分发。
（直接命令等价写法：`pyinstaller --onefile --windowed --name MySQLDiffTool main.py`）

### macOS → .app

在 Mac 上执行（任选其一）：

```bash
chmod +x build_macos.sh && ./build_macos.sh
```

或手动：

```bash
pyinstaller --noconfirm --clean MySQLDiffTool.spec
```

产物：`dist/MySQLDiffTool.app`。

未签名应用首次运行可能被 Gatekeeper 拦截，任选一种方式放行：

```bash
xattr -cr dist/MySQLDiffTool.app
# 或：右键 app → 打开 → 打开
```

> 提示：图标可在 `MySQLDiffTool.spec` 中配置 `icon="icon.ico"`（Windows）/
> `icon="icon.icns"`（macOS）。Windows 版只能在 Windows 上打包，macOS 版只能在 macOS 上打包
> （PyInstaller 不支持跨平台编译）。

## 四、实现要点

- **对齐与对比**：按 key 建哈希索引对齐两组结果；数字类型做容差比较
  （如 `Decimal('1.0')` 与 `1` 视为一致）；重复 key 取首行并在状态栏给出警告。
- **线程模型**：`FunctionWorker(QThread)` 在后台执行查询，通过 Qt 信号回传进度 / 结果 / 错误；
  界面只读不写，关闭 tab 时后台任务自动脱离并安全销毁。
- **过滤**：临时过滤直接在缓存结果上重新对比（不回查数据库）；固定过滤持久化到配置。
