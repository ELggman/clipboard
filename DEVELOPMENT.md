# Clipboard Workspace 开发文档

> 基于《Clipboard Workspace.md》需求文档编写。本文档是开发与打包的长期参考，随项目演进持续更新。
>
> 最后更新：2026-08-07（Session 会话机制落地，新增 §3.8/§7.2 v4）

---

## 1. 项目概述

macOS 本地剪贴板工作台：管理复制内容、实时搜索、快速粘贴、分类收藏、代码片段、快捷 Action，并预留 AI / OCR / 插件扩展能力。

V1.5 已落地 **Code Mode**（自动识别代码/语言、语法高亮、代码 Actions）与 **Privacy Mode**（暂停监控、来源应用排除、敏感内容检测与遮蔽、自动过期），核心检测 100% 本地（§3.6/§3.7）。

**设计原则**（不可妥协）：

- 全部数据本地存储，不上传、不依赖云服务
- 响应速度优先：启动 <1s，万条历史搜索 <100ms
- UI 简洁，macOS 原生观感，浅色/深色/跟随系统
- Actions 插件化，主程序不写死任何 Action

---

## 2. 技术栈与开发环境

### 2.1 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.12+ | 本机 3.13.9 |
| GUI | PySide6 (Qt6) | 本机 6.9.2 |
| 数据库 | SQLite + WAL | SQLAlchemy 2.0 ORM |
| 配置 | YAML | PyYAML |
| 图片 | Pillow | 缩略图、预览 |
| 语法高亮 | Pygments（纯 Python 本地） | Code Mode 详情页 8 类 token 高亮，懒导入 |
| 系统桥接 | pyobjc-framework-Quartz | 剪贴板监听、全局热键（CGEventTap） |
| OCR（V1.5） | PaddleOCR | 见 §7.3 打包注意事项 |
| 打包 | PyInstaller | 必须签名，见 §6 |

### 2.2 本机环境现状（2026-08-06 实测）

- macOS 26.0.1，Apple Silicon（arm64），Xcode Command Line Tools 已装（`codesign` 可用）
- Python 3.13.9（Anaconda：`/opt/anaconda3/bin/python3`）
- 已安装：PySide6 6.9.2、SQLAlchemy 2.0.43、Pillow 12.0.0、PyYAML 6.0.3、numpy 2.3.5、pyobjc-core/Cocoa/CoreServices 12.1
- **缺**：`pyobjc-framework-Quartz`、`pyperclip`、`PyInstaller`

### 2.3 环境搭建

**重要：不要直接在 Anaconda base 环境开发/打包。**

原因：Anaconda 携带大量无关包，PyInstaller 静态分析时容易把无关依赖打进去，导致体积膨胀、缺 dylib、排错困难。

```bash
# 在项目根目录创建独立 venv（基于系统 python3，pip 安装 PySide6 等）
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# 核心依赖
pip install PySide6 SQLAlchemy PyYAML Pillow pyobjc-framework-Quartz pyperclip

# 开发/打包依赖
pip install pyinstaller

# 导出依赖清单（分层，便于审阅）
pip freeze > requirements.lock
```

**注意：不要安装 `keyboard` / `pynput` 库。** macOS 下 pynput 调用 HIToolbox 会在监听线程触发主线程断言崩溃（EXC_BREAKPOINT）；`keyboard` 权限问题多。全局热键一律用自写 Quartz CGEventTap（见 §4.2）。

### 2.4 目录结构（在需求文档基础上扩展）

```
clipboard-workspace/
├── app/
│   ├── main.py              # 入口：单例、激活策略、启动顺序
│   └── __init__.py
├── actions/                 # 插件化 Action，每个文件一个 Action（运行时加载）
│   ├── __init__.py          # 加载器：扫描目录 + 统一接口
│   ├── json_pretty.py
│   ├── base64_encode.py
│   ├── base64_decode.py
│   ├── url_encode.py
│   ├── url_decode.py
│   ├── markdown_preview.py
│   ├── sort_lines.py
│   ├── remove_duplicate_lines.py
│   ├── upper_case.py
│   ├── lower_case.py
│   └── trim_space.py
├── database/
│   ├── engine.py            # SQLite + WAL + 连接配置
│   ├── models.py            # SQLAlchemy ORM 模型
│   └── migrations.py        # schema 演进（轻量：PRAGMA user_version）
├── services/
│   ├── clipboard_watcher.py # 剪贴板监听（NSPasteboard changeCount 轮询；含暂停）
│   ├── code_detector.py     # Code Mode：18 语言启发式检测（纯函数，<20ms）
│   ├── sensitive_detector.py# Privacy Mode：5 类敏感正则 + 遮蔽（纯函数）
│   ├── hotkey_manager.py    # 全局热键（CGEventTap，多绑定 ⌘⇧V / ⌘⇧P）
│   ├── search_service.py    # 搜索（FTS5 + CJK LIKE 兜底）
│   ├── snippet_service.py   # 变量替换 {{date}} {{time}} {{uuid}}
│   ├── action_service.py    # Action 注册与执行（复用 app/actions 接口）
│   └── image_service.py     # 图片落盘、缩略图缓存（失败不缓存）、删除保护
├── ui/
│   ├── main_window.py       # 主窗口（顶部导航 + 搜索栏 + 内容区 + 底部状态栏 + 隐私指示）
│   ├── quick_paste_popup.py # ⌘⇧V 弹出层
│   ├── item_detail_popup.py # 详情弹层（文本/图片/代码高亮/敏感 Reveal）
│   ├── code_highlighter.py  # Pygments → QSyntaxHighlighter（8 类 token，懒加载）
│   ├── history_view.py      # 历史列表（HistoryDelegate：文本/图片/代码/敏感/标题行）
│   ├── collections_view.py
│   ├── snippets_view.py
│   ├── timeline_view.py     # 时间线（复用 HistoryDelegate 渲染）
│   ├── settings_view.py     # 设置（含隐私区：策略/忽略应用/暂停监控）
│   ├── clean_data_dialog.py # 清理数据弹窗（时间+类型筛选删除）
│   ├── app_picker_dialog.py # 已安装应用选择器（忽略列表）
│   └── theme.py             # 浅色/深色/跟随系统（QPalette + Stylesheet）
├── resources/               # 图标、qss
├── config/
│   ├── settings.yaml        # 用户配置（运行时读）
│   └── defaults.yaml        # 默认配置（打包进 app）
├── packaging/
│   ├── build.sh             # PyInstaller 打包 + 签名 + 验证（来自 macos-packaging skill）
│   ├── make_cert.sh         # 自签名证书（每台机器一次，幂等）
│   ├── entitlements.plist   # Hardened Runtime
│   └── clipboard-workspace.spec
├── images/                  # 应用运行时图片数据（ApplicationData/Images 的别名）
├── logs/                    # 运行时日志
└── main.py                  # 入口（包装 app.main）
```

---

## 3. 核心架构决策

### 3.1 剪贴板监听

**选型：`NSPasteboard` 的 `changeCount` 轮询（Quartz/Cocoa），不用 pyperclip 轮询。**

- pyperclip 在 macOS 走 `pbpaste`/`pbcopy` 子进程，只适合主动读写，不适合后台常驻监听（进程开销、延迟）。
- `NSPasteboard.generalPasteboard().changeCount()` 是进程内 API，轮询间隔 ~0.2s，开销极小，实时性满足需求。
- **读取剪贴板不需要任何 TCC 权限**（pasteboard 不受 TCC 保护），这是本项目权限负担低的核心原因。

```python
from AppKit import NSPasteboard

class ClipboardWatcher(QObject):
    changed = Signal(object)  # 携带 (type, content, file_path)

    def __init__(self, poll_interval: float = 0.2):
        super().__init__()
        self._last_change = NSPasteboard.generalPasteboard().changeCount()
        self._timer = QTimer(self)  # 放在 Qt 事件循环里，天然主线程
        self._timer.timeout.connect(self._poll)
        self._timer.start(int(poll_interval * 1000))

    def _poll(self):
        pb = NSPasteboard.generalPasteboard()
        cc = pb.changeCount()
        if cc == self._last_change:
            return
        self._last_change = cc
        # 解析：先看 NSPasteboard.PasteboardTypeString / .PNG / .FileURL / .URL
        # 按顺序探测，落到 (type, content, file_path)
```

解析顺序（与需求一致：Text → URL → Image → File）：

1. `NSPasteboardTypeString` → Text（再按 `is_url` 判断 URL 类型）
2. `NSPasteboardTypePNG` / `NSPasteboardTypeTIFF` → Image（图片转存 + 缩略图，见 §3.5）
3. `NSFilenamesPboardType`（`NSPasteboardTypeFileURL`）→ File
4. 都不是 → 忽略

**`source_app` 获取**：在变化事件回调时刻取 `NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()`，不需要额外权限。

**去重**：内容 hash（sha256，图片 hash 图片二进制）。hash 相同 → 只更新 `updated_at` 不新增。

### 3.2 全局热键（⌘⇧V Quick Paste）

**选型：自写 Quartz `CGEventTap`，零依赖、不碰 HIToolbox。**

- 禁止 `keyboard`/`pynput`（崩溃原因见 §2.3）。
- 热键是物理键组合：用 **vk 码 + 修饰键掩码匹配，不需要键盘布局**。
- **需要「辅助功能」或「输入监控」TCC 权限**（监听键盘事件），权限处理见 §5。
- 回调内只做轻量操作，跨线程用 `QApplication.postEvent` 派发，避免死锁/崩溃。

```python
import Quartz

# vk 码：⌘=55, ⇧=56, V=9
mask = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift
tap = Quartz.CGEventTapCreate(
    Quartz.kCGHIDEventTap,
    Quartz.kCGHeadInsertEventTap,
    Quartz.kCGEventTapOptionDefault,
    Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
    callback, None)

def callback(proxy, event, refcon):
    flags = Quartz.CGEventGetFlags(event)
    if flags & mask == mask and Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode) == 9:
        # 过滤自动重复
        if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
            return event
        QApplication.postEvent(win, PopupEvent())  # 主线程弹 Quick Paste
        return None  # 消费按键
    return event
```

要点：

- tap 跑在 daemon 线程的 CFRunLoop 里（`CFRunLoopAddSource`），回调勿做重活
- `CGEventTapCreate` 返回 None → 明确的错误日志（未授权/沙箱拦截）
- 录制模式（Settings 里改快捷键）回调返回 None 消费事件
- 热键触发弹窗时，若应用是 accessory（LSUIElement），需先处理激活策略，否则窗口不渲染（见 §4.3）

**多绑定（V1.5）**：`HotkeyManager` 持 `_bindings: [(vk, mask, Signal)]`，一个 CGEventTap 遍历匹配。
`activated`（⌘⇧V=9，Quick Paste）+ `privacy_toggle`（⌘⇧P=35，隐私暂停，见 §3.7）。
vk 码与键盘布局无关（物理键）。

### 3.3 Actions 插件系统（全项目最值得投入的设计）

需求文档明确：Actions 不写死，新功能 = 新增一个插件文件。**V1 就按此设计，后续 AI / OCR / 格式化都是插件的增量。**

统一接口（放 `actions/base.py`）：

```python
class ClipboardAction(ABC):
    id: str                 # 唯一标识，如 "json_pretty"
    name: str               # 显示名
    icon: str               # 图标资源名

    def can_handle(self, clipboard_item) -> bool: ...
    def execute(self, clipboard_item) -> None:   # 结果写回剪贴板
```

加载器（`actions/__init__.py`）：

```python
def load_actions(extra_dirs: list[Path] = ()) -> list[ClipboardAction]:
    """扫描内置 actions/ 目录 + 用户插件目录，importlib 动态加载"""
```

**PyInstaller 关键坑：运行时加载的 .py 文件不会被静态分析收集。** 内置 actions 要么显式在 spec 里 `collect_submodules('actions')`，要么把内置目录声明为 data 文件；用户插件目录（如 `~/Library/Application Support/ClipboardWorkspace/actions/`）则天然不打包，运行时扫描即可。

### 3.4 搜索性能（10k 条 <100ms）

- SQLite 开 **FTS5**，对 `clipboard_items.content` 建全文索引，普通搜索走 FTS5 匹配（模糊、忽略大小写天然满足）
- **中文搜索**：FTS5 unicode61 把连续中文当一个 token，子串匹配不上（实测「胶原」搜不出「最近胶原蛋白满满」）→ 查询含 CJK 时改走 `LIKE '%词%'` 子串扫描（10k 行毫秒级，含通配符转义），ASCII 仍走 FTS5
- Regex 高级模式：`LIKE`/`REGEXP` 兜底，数据量 10k 级别同样 <100ms，无需优化
- 结果分页加载（每页 50–100 条），UI 用 Qt Model/View + `QSortFilterProxyModel` 局部刷新
- 排序：最新优先（`created_at DESC` 索引）

### 3.5 图片处理

- 图片不入库：落盘 `ApplicationData/Images/<hash>.png`，DB 只存 `file_path`
- 缩略图：生成 <256px 缓存到内存 LRU（QImage），列表展示用
- 懒加载：滚动到可视区域才生成/读取缩略图（`setItemPrototype` + 手动触发）
- **失败不缓存（关键）**：`@lru_cache` 会缓存 None 返回值——文件缺失的失败被永久缓存，文件重建后永远返回 None（实测：历史/收藏全部缩略图消失，重启才恢复）。解码走 `_thumbnail_cached`（lru_cache 只缓存成功），失败抛异常走未缓存入口重试
- **删除保护（关键）**：`delete()` 只允许删除 `images/` 目录内文件（`is_managed` 守卫）。
  FILE 条目的 `file_path` 指向用户**原始文档**，无条件 unlink 会把用户文件删掉（实测数据丢失）；删除前再查 `collection_service.is_file_path_referenced`——被收藏快照引用的图片保留（否则收藏粘贴失效）

### 3.6 Code Mode（代码模式，新增.md §8）

**定位**：内容状态而非开关——剪贴板文本到达时自动检测，置信度 ≥0.80 才标 `type="code"`；低于阈值保留 `language` 作辅助字段。100% 本地，检测 <20ms。

**检测器（`services/code_detector.py`，纯函数零 Qt/DB 依赖）**：

- 18 语言启发式打分（python/javascript/typescript/java/c/cpp/csharp/go/rust/swift/kotlin/sql/shell/html/css/json/yaml/markdown），每语言关键字集 + 结构信号
- `detect(content) -> CodeResult(language, confidence, is_structured) | None`；`CODE_THRESHOLD = 0.80`
- 结构化优先：JSON 解析成功即 1.0（is_structured=true）；YAML 解析前须过键值结构占比门槛（PyYAML 能把 Python 代码解析成 dict，实测踩坑）
- 性能：<2 行快速退出（单行另查 shell/rust/sql/yaml 强信号）、分析截断 4096 字符
- **误判防护（实测踩坑）**：`#include` 等预处理器不计为 shell 注释；`<int>` 泛型不计为重定向（`(?<![<\w])>` 限定）；python 缩进加分要求强信号 ≥2（单行 import+缩进曾把 Swift 结构体判成 Python）

**接入点**：`ClipboardWatcher._parse` 文本分支——url 判断后跑 `detect`，命中则携带 language/confidence/line_count/character_count/is_structured 落库（v3 列，见 §7.2）。

**UI**：

- 列表：`_draw_code_row`——语言 emoji 徽标（🐍 Python）+ mono 预览 ≤6 行 + `+N more lines` + 行数；meta 行基线 33 与文本行一致
- 详情弹窗：`_CodeView`（独立行号 gutter 组件 + 只读 mono 编辑区）+ `CodeHighlighter`（Pygments 懒导入，8 类 token 映射 QTextCharFormat，颜色按深浅主题取 GitHub 系配色）
- 复制按钮：有选中复制选中部分（selectedText 的 U+2029 还原为换行），无选中复制全部
- 代码 Actions：添加/移除行号、JSON 压缩/校验、检测语言、保存为文件（扩展名映射表）、复制纯文本（markdown 剥离）；`json_pretty` 兼容 code 类型

**坑**：Pygments 2.x 的 token 是 `_TokenType` **实例**，层级在 `parent` 链（`type(token).__mro__` 是元类链，永远匹配不上，实测零高亮）；`setViewportMargins` 会被 QSS padding 在渲染层覆盖（文本压到行号区）→ 行号用独立组件；macOS 透明 QPlainTextEdit viewport 首行合成异常 → 背景不透明。

### 3.7 Privacy Mode（隐私模式，新增.md §9）

**管线（`bootstrap.apply_privacy_policy`，on_clipboard_changed 前置）**：

```
剪贴板变化 → 暂停? → 来源应用 ∈ 忽略列表? → 敏感检测(text/code) → 落库
                        ↓                ↓                    ↓
                   跳过(日志)       跳过(日志)      warn: sensitive=1 保存
                                                 ignore: 跳过
                                                 save_temporarily: expires_at
```

- **暂停监控**：⌘⇧P 切换（watcher `paused`——poll 仍记录 changeCount，恢复不爆发补抓），状态栏永久控件 📋/🔒
- **应用排除**：`privacy.ignored_apps` 配置 + 已安装应用选择器（扫描 /Applications、~/Applications、/System/Applications 的 .app 读 Info.plist 显示名 + 运行中常规应用，搜索过滤）
- **敏感检测（`services/sensitive_detector.py`，纯函数）**：api_key/token/jwt/私钥/password 五类正则；**URL 一律跳过**（微信分享链接的 token= 查询参数是常态，误判噪声大于收益）
- **遮蔽**：warn 策略下 DB 保留原文、显示层 mask（`sk-••••••`、私钥整体隐藏、手动标记整段遮蔽）；详情弹窗「显示」Reveal 切换
- **手动标记**：右键菜单「标记为敏感/取消敏感标记」（`history_service.set_sensitive`，类型 manual）
- **自动过期**：save_temporarily 写 `expires_at`，`delete_expired` 清扫（启动 60s + 每 24h，与 auto_delete 同 timer）；置顶条目豁免自动删除（§9.22，含 save_item 内联 trim）
- **日志规范（§9.23）**：一律不含剪贴板原文——`reason=application_exclusion` / `type=api_key action=warn` 结构，搜索日志不记查询词
- **删除保护**：见 §3.5——删除历史只清理受管图片，绝不碰用户文档

### 3.8 Session 会话机制（v4）

**定位**：任务型内容分组。论文翻译/写作优化等场景的大量复制粘贴会把其他内容挤到很靠后、次日难以找回——会话把内容按任务隔离。默认「普通」会话接收所有内容；可新建任务会话并**激活**，激活期间新复制内容保存到该会话；可随时切回普通。

**数据**：`sessions` 表（id/name/is_default/created_at，默认 id=1「普通」）+ `clipboard_items.session_id`（v4 迁移，旧数据默认归普通）。

**服务（`services/session_service.py`）**：

- `ensure_default`（幂等，启动调用）/ `list_sessions`（含 count）/ `create` / `rename` / `delete`
- `delete_session`：**内容移回普通会话**（`UPDATE session_id=1`）——会话是临时分组，内容不丢；默认会话禁删禁改名
- 激活持久化：`config/settings.yaml` 的 `session.active_id`，切换即写回，**重启恢复上次激活的会话**（次日继续任务的核心场景）

**查询过滤**：`history_service.list_recent / search_items / list_grouped / list_older_than` 全部加 `session_id: int | None = None`（None=全部，旧调用兼容）；`search_service.search` 三条路径（FTS5/LIKE/regex）同样支持。

**UI**：

- 历史页顶部**会话下拉**（「普通 · 33 条」）+ ⋯ 管理菜单（新建/重命名/删除当前，删除红色确认提示"内容将移回普通"）；下方类型筛选 tabs 保持不变
- 启动恢复仅加载**激活会话**内容；其余会话通过下拉切换查看
- 搜索框旁**范围下拉**（全部会话/本会话）；全局搜索结果 meta 行加 `[会话名]` 前缀（delegate `_session_tag`：仅当条目不属于当前视图会话时标注——会话视图内不冗余）
- 清理数据弹窗加会话筛选维度
- 置顶在会话视图内正常（list_recent pinned DESC）；收藏快照独立不受影响；时间线保持全局

**坑**：会话下拉必须在 bootstrap 装配时显式 `reload_sessions(active_id)` 填充（仅注入 context 不会填充，实测下拉空）。

---

## 4. 应用形态与 macOS 集成

### 4.1 单实例与常驻

- 菜单栏常驻（需求要求开机启动）→ **accessory 应用**：`Info.plist` 设 `LSUIElement=1`
- 单实例：main.py 里用 POSIX socket / `QLocalServer` 检测已有实例，新实例向旧实例发信号（例如唤起 Quick Paste）后退出

### 4.2 开机启动

标准做法：`~/Library/LaunchAgents/com.clipboardworkspace.app.plist`，`RunAtLoad=true`，由应用「设置 → 开机启动」开关管理（写入/移除 plist + `launchctl`）。

### 4.3 accessory 应用的窗口渲染坑

accessory 应用非激活时，Qt 顶层窗口不绘制（已实测）。影响：Quick Paste 弹出层、悬浮提示。

对策（打包版尤其要验证）：

1. 弹 Quick Paste 前 `QApplication.setQuitOnLastWindowClosed(False)` 保持后台
2. 需要弹窗时临时 `activate()`（`processEvents` 后建窗），或
3. 通知类内容用 `osascript -e 'display notification ...'`（Qt `QSystemTrayIcon.showMessage` 依赖废弃的 NSUserNotification，不可靠）

---

## 5. TCC 权限与签名（打包核心）

### 5.1 本项目需要哪些权限

| 能力 | 权限 | 是否必需 |
|---|---|---|
| 剪贴板监听/读写 | 无（pasteboard 不受 TCC 保护） | — |
| 全局热键 ⌘⇧V | **辅助功能** 或 **输入监控** | V1 必需 |
| 屏幕录制 | 不需要（本应用不抓屏） | — |
| OCR（V1.5） | 无（处理已有图片） | — |

所以 V1 只有热键一条权限链路，务必处理干净。

### 5.2 签名铁律（来自 macos-packaging skill）

1. **绝不用 ad-hoc 签名（`codesign --sign -`）**。TCC 权限绑定 cdhash，ad-hoc 每次构建二进制变化 → 所有已授权限被悄悄清空 → 「权限反复失效 / 热键失效 / 反复弹授权」。
2. **必须用带身份的签名**：自签名证书（免费，本机一次）或 Apple Developer 证书（分发公证）。本项目先自签名。
3. **不要改 bundle identifier 和签名证书**——改了，用户全部已授权限作废。
4. 事件监听跑在主进程内，不要 multiprocessing spawn（TCC 归属断裂）。

### 5.3 辅助功能权限处理（热键）

辅助功能**没有程序化申请 API**（输入监控也没有）。正确流程：

- 启动时 `AXIsProcessTrusted()`（ctypes 加载 ApplicationServices 多路径）检测
- 未授权 → 引导窗口：显示状态 + 「打开系统设置」按钮（`open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"`）
- CGEventTap 创建失败时给出明确错误（而非静默失效）
- **检测用实时 preflight，不依赖「已提示」标记**

```python
def ensure_accessibility() -> bool:
    if ax_is_trusted(): return True
    if not _guide_shown:            # 每进程至多一次
        _guide_shown = True
        show_guide_dialog()         # 状态 + 打开设置按钮
    return False
```

### 5.4 授权条目混淆的坑

系统设置里同名条目可能绑定旧构建的 cdhash（死条目）。用户「授权了仍无效」时：移除旧条目，用「+」按应用完整路径重新添加当前构建。

---

## 6. 打包与发布管线

### 6.1 一次性准备（每台打包机器一次）

复制 `packaging/make_cert.sh`，改 `CERT_COMMON_NAME`（如 `Clipboard Workspace Dev`），运行（幂等）。用 `openssl pkcs12 -export -legacy` 兼容 `security import`（openssl 3.x PBES2 会报 MAC verification failed）。

### 6.2 每次构建（build.sh 流程）

1. `pkill` 旧实例（防 `rm -rf dist` 失败）
2. PyInstaller 打包：**用 onedir**（onefile 冷启动解压慢，冲击 <1s 目标）；spec 里：
   - `collect_submodules('actions')` 内置插件
   - 排除用户插件目录（运行时加载）
   - `LSUIElement=1`、bundle id 固定、版本号
3. 自签名证书签名 + entitlements.plist（Hardened Runtime）
4. 验证：
   - `codesign -d -r- <app>` 显示 `certificate` 而非 `cdhash`
   - 启动、热键、权限引导三条链路可用
   - **授权一次 → 重建两次 → 权限仍有效**（终极验收）

### 6.3 启动 <1s 的达成路径

- PySide6 + SQLAlchemy import 本身 ~0.5s+，**全部业务模块懒加载**：main.py 只 import Qt 核心，UI/服务按需 `importlib` 或模块内延迟导入
- 数据库连接延迟到首次查询
- onedir 打包、配置读 YAML 用 `yaml.safe_load`（避免 ruamel 慢路径）
- 打包后实测：`/usr/bin/time <app>` 多次取中位数，CI 校验 <1s

### 6.4 V1.5 打包预警：PaddleOCR

- paddle / paddleocr 体积数百 MB，PyInstaller 需 `collect_all` + 专用 hooks，且 arm64 wheel 兼容性要验证
- 建议：OCR 作为独立插件（§3.3 架构天然支持），独立打包/独立安装，不进主包
- V1 阶段完全不引入，只留接口

---

## 7. 数据库设计

### 7.1 SQLite 配置

- `PRAGMA journal_mode=WAL`（连接时通过 SQLAlchemy event 设置）
- `PRAGMA foreign_keys=ON`（collection_items 外键）
- 迁移：`PRAGMA user_version` 版本号递增 + 迁移脚本列表（轻量够用，不引 Alembic）

### 7.2 表结构（按需求文档 + FTS 补充）

```sql
CREATE TABLE clipboard_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,          -- text / url / image / file / code
    content     TEXT,                   -- 文本内容（url 存 URL；image/file 存路径；code 存源码）
    preview     TEXT,                   -- 列表预览文案
    file_path   TEXT,                   -- image/file 的存储路径
    hash        TEXT UNIQUE NOT NULL,   -- 去重
    source_app  TEXT,                   -- 来源应用
    favorite    INTEGER DEFAULT 0,
    pinned      INTEGER DEFAULT 0,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    -- v4（Session 会话，2026-08-07）：所属会话，默认 1 = 普通
    session_id  INTEGER NOT NULL DEFAULT 1,
    -- v3（Code Mode / Privacy Mode，2026-08-07）
    language            VARCHAR(32),    -- 检测语言（code 必有；text 可留辅助字段）
    language_confidence REAL,           -- 0.0-1.0
    line_count          INTEGER DEFAULT 0,
    character_count     INTEGER DEFAULT 0,
    is_structured       INTEGER DEFAULT 0,  -- json/yaml/sql
    sensitive           INTEGER DEFAULT 0,  -- 敏感标记（warn/manual）
    sensitive_type      VARCHAR(32),        -- api_key/token/jwt/private_key/password/manual
    expires_at          DATETIME            -- 临时条目到期时间（save_temporarily）
);
CREATE INDEX ix_items_created ON clipboard_items (created_at DESC);
CREATE INDEX ix_items_type    ON clipboard_items (type);
CREATE INDEX ix_items_expires ON clipboard_items (expires_at);
CREATE VIRTUAL TABLE items_fts USING fts5(content, content='clipboard_items', content_rowid='id');

CREATE TABLE collections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    icon       TEXT,
    created_at DATETIME NOT NULL
);

-- v2 起为内容快照（与历史解耦）：删除历史不影响收藏
CREATE TABLE collection_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
    clipboard_id  INTEGER,              -- 来源引用（无 FK，可能悬空）
    type          TEXT NOT NULL DEFAULT 'text',
    content       TEXT,                 -- 内容冗余快照
    preview       TEXT,
    file_path     TEXT,                 -- 图片快照路径（被引用时删除历史保护该文件）
    created_at    DATETIME NOT NULL,
    UNIQUE (collection_id, clipboard_id)
);

CREATE TABLE snippets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    content     TEXT NOT NULL,
    description TEXT,
    created_at  DATETIME NOT NULL
);

-- v4：会话（任务型内容分组，默认「普通」id=1 不可删）
CREATE TABLE sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       VARCHAR(128) NOT NULL,
    is_default INTEGER DEFAULT 0,
    created_at DATETIME NOT NULL
);
CREATE INDEX ix_items_session ON clipboard_items (session_id);
```

- FTS5 同步：应用层在插入/删除后同步更新 items_fts（10k 量级足够，不引触发器）；code 内容正常全文检索
- 自动删除策略（1/7/30/90/365 天/永不）：后台 `QTimer` 每日扫描一次，删除时同步删**受管**图片文件（置顶豁免，§9.22）
- 历史数量上限（100/500/1000/无限）：插入前裁剪最旧记录（**置顶优先豁免**，与 list_recent 排序一致）
- 迁移：`PRAGMA user_version`（当前 = 4）；v2 快照化、v3 加元数据列、v4 会话均用 `PRAGMA table_info` 防重 + ALTER TABLE（新列全部 nullable 或带 DEFAULT，SQLite 限制）
- 文件大小上限：`history.max_file_size_mb`（默认 50MB，0=不限制），on_clipboard_changed 对 FILE 类型 stat 超限跳过
- 会话：`sessions` 表 + `clipboard_items.session_id`（§3.8）；默认会话幂等创建

### 7.3 Snippet 变量

`{{date}}` → 当日日期、`{{time}}` → 当前时间、`{{uuid}}` → uuid4。渲染逻辑放 `services/snippet_service.py`，支持后续扩展变量。复制时渲染成最终文本。

---

## 8. 开发规范

1. **日志**：`logging` 到 `logs/` + 按天滚动。**windowed 应用 stderr 不可见，所有槽函数 try/except + `log.error`，禁止裸异常**（打包版异常静默是最大排查障碍）
2. **线程模型**：Qt 主线程跑 UI 和监听（QTimer）；重任务（缩略图、PaddleOCR）用 `QThreadPool`，**结果通过 signal 回主线程**，禁止跨线程碰 QWidget
3. **Action 插件**：只依赖 `ClipboardAction` 接口，主程序不 import 具体实现（保证「加 Action 不改主程序」）
4. **代码风格**：类型注解 + docstring；模块内私有函数 `_` 前缀
5. **配置**：`config/defaults.yaml` 打包内置，用户配置写 `config/settings.yaml`，缺失字段回退默认值（`defaults` 合并）
6. **测试**：核心服务（去重、搜索、变量渲染、Action 加载器、检测器）写 pytest；UI 层人工验收清单
7. **隐私日志（§9.23，不可妥协）**：日志一律不含剪贴板原文。剪贴板内容只记 `type` + `hash[:8]`；跳过/敏感事件用结构化字段（`reason=application_exclusion`、`type=api_key action=warn`）；搜索日志不记查询词
8. **git**：目录非 git 仓库——建议 `git init` 后提交初始版本，`packaging/` 与 `logs/`、`images/` 进 `.gitignore`

---

## 9. 已踩过的坑速查（macos-packaging skill 适配）

| 症状 | 根因 | 解决 |
|---|---|---|
| 打包版热键失效（dev 正常） | pynput 主线程断言崩溃 / 子进程 TCC 断裂 | 自写 CGEventTap 主进程内 |
| 重建后权限全丢、反复弹授权 | ad-hoc cdhash 变化 | 自签名证书 |
| 系统设置授权了仍无效 | 授权落在旧 cdhash 死条目 | 移除旧条目 + 按路径重新添加 |
| accessory 应用弹窗不渲染 | 非激活时 Qt 顶层窗口不绘制 | 临时 activate 或 osascript 通知 |
| 打包版异常静默 | windowed 应用 stderr 不可见 | 槽函数 try/except + log.error |
| `security import` MAC verification failed | openssl 3.x PBES2 不兼容 | `openssl pkcs12 -export -legacy` |
| Actions 运行时加载失败 | PyInstaller 静态分析收集不到 | spec `collect_submodules` / 外部插件目录 |
| 构建 `rm -rf dist` 失败 | 旧实例占用 | build.sh 先 pkill |
| 清理数据把用户原文档删了 | FILE 条目 file_path 指向用户文档，删除无条件 unlink | `is_managed` 守卫只删 images/ 内文件（§3.5） |
| 收藏夹图片粘贴失效 | 删除历史清理了被收藏引用的图片文件 | 删除前查 `is_file_path_referenced`（§3.5） |
| 历史/收藏全部无缩略图，重启恢复 | `@lru_cache` 缓存了失败 None（文件缺失毒化） | 失败抛异常不缓存，`_thumbnail_cached` 只缓存成功（§3.5） |
| 代码详情无高亮 | Pygments 2.x token 是 `_TokenType` 实例，`type(token).__mro__` 取元类链 | 遍历 `token.parent` 链匹配（§3.6） |
| 代码文本压到行号区 | QSS padding 渲染层覆盖 `setViewportMargins` | 行号改独立 gutter 组件（§3.6） |
| 代码首行显示不全 | macOS 透明 QPlainTextEdit viewport 合成异常 | 背景不透明 `$window`（§3.6） |
| C++ 判成 shell | `#include` 计为 shell 注释、`<int>` 计为重定向 | 预处理器排除 + `(?<![<\w])>` 限定（§3.6） |
| Swift 判成 Python | import+缩进加分过宽 | 缩进加分要求强信号 ≥2（§3.6） |
| 微信 URL 判成敏感 | 分享链接 token= 查询参数命中 token 正则 | URL 类型跳过敏感检测（§3.7） |
| 复制新文本把置顶挤下去 | add_item 固定插行 0 | 插到置顶组之后（pinned DESC 一致） |
| 会话下拉为空 | 只注入 context 未填充下拉 | bootstrap 装配时显式 `reload_sessions(active_id)`（§3.8） |
| 全局搜索看不到会话来源 | 条目未带 session 名 | `_to_item` LEFT JOIN sessions 填 `session_name`，delegate `_session_tag` 标注（§3.8） |

---

## 10. Roadmap 映射

| 版本 | 内容 | 本文档对应 |
|---|---|---|
| V1 | 文本/图片/URL/文件历史、搜索、收藏、Snippet、Action | §3 全部就绪 |
| V1.5 | 代码/图片/敏感条目渲染、列表卡片底色、详情弹窗、清理数据弹窗 | §3.5/§3.6 就绪 |
| V1.5 | **Session 会话**（任务分组/激活切换/搜索范围/来源标注） | §3.8 就绪 |
| V1.5 | **Code Mode**（代码检测/语言识别/语法高亮/代码 Actions）、**Privacy Mode**（暂停监控/应用排除/敏感检测/遮蔽/自动过期） | 新增.md §8/§9，本版本已完成 |
| V1.5 | OCR、图片预览、拖拽、多窗口 | OCR 插件化（§6.4），拖拽/多窗口在 ui/ 层扩展 |
| V2 | AI 插件（Summarize/Translate/Rewrite/Explain） | 需 AI Privacy Gateway（新增.md §9.25）后启用 |
| V3 | 第三方插件、开放 API | §3.3 加载器支持用户插件目录，即 V3 雏形 |

**设计校验原则**：任何新功能，先问「能否作为 Action / 插件增量加入？」——能，则主程序不动；不能，才允许改核心。

---

## 11. 下一步 TODO（按序）

- [x] `git init` 初始化仓库 + `.gitignore`（venv、dist、logs、images）
- [x] 搭建 venv，补齐依赖（pyobjc-framework-Quartz、pyinstaller）
- [x] 按 §3.1 落地 ClipboardWatcher（文本/URL/图片/文件监听 + 去重 + SQLite 落库）
- [x] 按 §3.2 落地 CGEventTap 热键（辅助功能引导窗口 V1.5）
- [x] 主窗口骨架（顶部导航/搜索栏/状态栏/主题切换）
- [x] Actions 接口 + 内置 11 个 Action
- [x] Quick Paste 弹窗闭环（⌘⇧V → 最近 10 条 → Enter 回写剪贴板）
- [x] 搜索栏接线（防抖 150ms + FTS5 过滤，清空恢复完整历史）
- [x] 右键菜单（Copy / Pin / Favorite / Add To Collection / Action 子菜单）
- [x] 设置页 UI（主题/字体/历史数量/图片保存/图片文件名/自动删除/开机启动；快捷键展示，自定义 V1.5）
- [x] 自动删除定时清扫（每日 + 启动 1 分钟后；置顶条目豁免；FTS 用 rebuild 重建避免外部内容表 DELETE malformed）
- [x] 开机启动 LaunchAgent（services/autostart.py；打包版替换 .app 路径）
- [x] Collections 收藏夹页（新建/重命名/删除/条目浏览/右键加入收藏夹/Actions）
- [x] Snippet 片段页（CRUD + 复制渲染 {{date}}/{{time}}/{{uuid}}）
- [x] Timeline 时间线页（今天/昨天/本周/更早按月分组，点击进详情）
- [x] **Code Mode**：代码检测（services/code_detector.py，18 语言启发式 + 置信度）+ v3 迁移元数据 + 列表 mono 预览 + 详情 Pygments 高亮 + 7 个代码 Actions
- [x] **Privacy Mode**：⌘⇧P 暂停监控 + 来源应用排除 + 敏感检测（warn/ignore/临时过期）+ 遮蔽显示 + ⌘Delete 手动删除
- [ ] 一次性准备打包：make_cert.sh 生成自签名证书
- [ ] build.sh 打通「打包 → 签名 → 验证 checklist」
- [ ] 性能验收：启动 <1s、万条搜索 <100ms
