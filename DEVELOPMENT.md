# Clipboard Workspace 开发文档

> 基于《Clipboard Workspace.md》需求文档编写。本文档是开发与打包的长期参考，随项目演进持续更新。
>
> 最后更新：2026-08-07（会话去重范围与删除策略可配置，v5）

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
│   ├── animations.py        # 动画/滚动基础设施（滚轮缓动、逐项入场、帧率时钟）
│   ├── scroll_fx.py         # 滚动视觉装饰（悬浮条/边缘渐隐/视差/抬升/景深）
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

解析顺序（**图片最优先**，代码为准）：

1. `NSPasteboardTypePNG` / `NSPasteboardTypeTIFF` → Image（转存 + 缩略图，见 §3.5）。
   ⚠️ **必须排在 File 之前**：应用内复制图片（截图 / VS Code / Safari）时剪贴板常
   同时带 file-url 与图片数据，用户意图是图片内容；只有 file-url（无图片数据）才是
   文件复制。
   ⚠️ **例外：表格复制的细长位图**（`_is_table_strip`，见 §9「Excel 整列复制」）。
2. `NSPasteboardTypeFileURL` → File（路径 percent-decode，否则中文名显示乱码）
3. `NSPasteboardTypeURL` → URL；`NSPasteboardTypeString` → URL/Code/Text
   （http(s) 开头视为 URL；再走 `code_detector`，置信度 ≥0.80 记 code）
4. 都不是 → 忽略

**`source_app` 获取**：在变化事件回调时刻取 `NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()`，不需要额外权限。

**去重**：内容 hash（sha256；图片 hash **落盘 PNG 字节**而不是剪贴板原始字节——
剪贴板可能是 TIFF，重新复制同一张图时拿到的是 PNG，按原始字节算会让去重永久失效，
见 `ImageService.save` 的 docstring）。hash 相同 → 只更新 `updated_at` 不新增。

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

- 历史列表键盘/手势（eventFilter，列表获得焦点时生效）：
  - **←/→ 键**循环切换类型筛选（全部/文本/URL/图片/文件/代码）
  - **触控板双指左右滑**：拦截 viewport 的 Wheel 事件（QAbstractScrollArea 滚轮在 viewport 上，须对 viewport 装 eventFilter），x 分量主导时切换。**判定 = Begin 后首个非 Begin 事件**：`Update` → 手指段（用户滑动）切 1 格；`Momentum` → 动量段不切（锁死）。⚠️ 探针实测 458 事件的真实结构：**一次物理滑动 = 手指段 `Begin→Update×N→End` + 动量段 `Begin→Momentum×N→End`**——动量开始也被系统标成 `ScrollBegin`，段间 End→Begin 间隔 <65ms（时间窗口方案全不可靠：250/400ms 都会多切/漏切）；同一次滑动还可能出现多个 Begin（`Begin(-16)→Begin(0)→Update(-34)`），也不能「见 Begin 就切」。连续 Begin 吞；Begin dx=0 由首个非零 Update 补切。**纵向事件全放行（含 Momentum 动量——曾无条件吞掉导致惯性滚动失效、下滑变一格一格）且不改变手势状态**；End 也放行（无 delta 无害）。双指向左滑 → 下一类型（类翻页语义）
  - 类型 tabs 构建时必须 `setCurrentRow(0)`：否则 `currentRow=-1` 无选中态（默认「全部」无高亮），且首次 ←/→ 落在 0 而非相邻项（实测）
- SQLite 开 **FTS5**，对 `clipboard_items.content` 建全文索引，普通搜索走 FTS5 匹配（模糊、忽略大小写天然满足）
- **中文搜索**：FTS5 unicode61 把连续中文当一个 token，子串匹配不上（实测「胶原」搜不出「最近胶原蛋白满满」）→ 查询含 CJK 时改走 `LIKE '%词%'` 子串扫描（10k 行毫秒级，含通配符转义），ASCII 仍走 FTS5
- Regex 高级模式：`LIKE`/`REGEXP` 兜底，数据量 10k 级别同样 <100ms，无需优化
- 结果分页加载（每页 50–100 条），UI 用 Qt Model/View + `QSortFilterProxyModel` 局部刷新
- 排序：最新优先（`created_at DESC` 索引）

### 3.5 图片处理

- 图片不入库：落盘 `ApplicationData/Images/<hash>.png`，DB 只存 `file_path`
- 缩略图：长边 **512px**（`THUMB_SIZE`），落盘 + 内存 LRU 两级缓存，列表展示用。
  **2026-09-30 由 256 提到 512**（用户报「缩略图看不清」）：列表行已改 68px 高、
  缩略图框最宽 2.5×68=170 逻辑 px，Retina 下要 340 物理 px，256px 源已经不够。
  后缀里带尺寸（`.t512.png`），将来再调只改 `THUMB_SIZE` 常量、老文件自动失效
  重生成；旧 256px 文件（`.thumb.png`）在重写/删除时顺手清掉
  （`_LEGACY_THUMB_SUFFIX`）。**只修分辨率、不动行高**（用户确认档位）
- **缩略图两级缓存（关键，2026-09-30）**：① 磁盘级 `images/<digest>.t512.png`
  ——`save()` 时顺手落盘（此处原图已解码在手，边际 ~0.5ms），老条目首次用到时
  懒回填；② 内存级 `@lru_cache(maxsize=128)`（同一屏反复绘制免重复读盘）。
  为什么两级都要：`lru_cache` 与 delegate 的 QPixmap 缓存**都只活在当前进程**，
  每次冷启动第一次滚到图片都要重解原图。实测解码 3.04ms vs 读落盘小文件 0.149ms
  （**差 20×**），而图片列表首轮滚动中位 9.77ms / p95 16.23ms / 最大 29.64ms
  ——**直接吃掉 60fps 的 16.7ms 预算**。落盘后同场景中位 1.28ms、零帧超预算。
  落盘缩略图与直接解码**逐像素一致**（读回后统一 `convertToFormat(RGBA8888)`，
  同一格式契约），像素缓存刷掉不能改变画出来的东西。
  只对**受管**路径落盘（`is_managed` 守卫）——FILE 条目指向用户原始文档，绝不
  往用户目录写 `.t512.png`。`delete()` 连带删掉小文件。预热
  `ImageService.prefetch(paths)` 用后台守护线程（纯 PIL + 文件 I/O，**不碰任何
  Qt 对象**，故无线程亲和性问题）把老条目成批转成小文件
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
- `delete_session(sid, policy)`：默认会话禁删禁改名。
  **policy 可配置（`session.delete_policy`）**：
  - `move`（默认）：内容移回普通并**合并去重**（普通已有同 hash 跳过，
    不产生跨会话重复）——先取数据再删再插（同表 INSERT SELECT 有 id
    冲突与孤儿 session_id 两个坑，实测）
  - `delete`：内容直接删除，图片路径返回调用方按引用保护清理
- **去重范围可配置（`history.dedupe_scope`）**：`all`（默认，全局去重，
  同内容任意会话命中即去重）/ `session`（仅本会话去重，跨会话同内容
  各存一份）。DB 唯一键 v5 起为 `(hash, session_id)`（SQLite 重建表），
  scope=all 时由 save_item 查重逻辑维持全局语义
- 图片清理保护：删除历史时 `is_path_still_referenced`（查其他会话行 +
  收藏快照）——按会话去重后同一图片文件被多会话引用，无引用才删
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

### 4.0 UI 设计语言（Raycast / macOS Sonoma 风格，用户确认规范）

- **整体**：简洁 / 高级 / 大量留白 / 卡片化（白色卡片 16px 圆角）/ 轻量阴影
  （Qt QSS 无 box-shadow，用 1px separator 描边 + 背景对比，Sonoma 同款）/
  蓝色主操作色（#007AFF 浅 / #0A84FF 深，accent）
- **顶部导航**：品牌行「Clipboard Workspace」+ 胶囊标签行。默认 16px #666
  （次要色）；**选中 = 蓝胶囊** #007AFF 白字 10px 圆角 padding 8px 22px；
  图标 🕐/⭐/📋/📈/⚙️ 由 `NavItemDelegate` QPainter 自绘（emoji 字形
  可靠路径；QPushButton 图标/emoji 会空白——本会话血泪史）
- **窗口**：默认 760×700，最小 640×560（编辑器弹窗化后模板页只需两栏）。
  ⚠️ HistoryView 缩放封顶 `min(width/380, 1.35)`——宽屏下 1000/380=2.63 倍
  会把行高/字号放得不可用，封顶后宽屏只增加留白
- **设置页 = 轻分组 + 行内说明**（2026-10-12，用户报「与后台管理系统太类似」）。
  原来是**一整列 `QFormLayout`**：标签右对齐压到中间、24 行同权重、只有两行灰字
  当分节——读起来就是「字段名 + 控件」的字段表。现在按
  **组标题（`QLabel#sectionTitle`）→ 组内细分隔线（`QFrame#settingsDivider`）
  → 每行「左列标题 + 标题正下方一行小字说明」+ 右列控件**排（macOS 系统设置的
  读法）。三条约定：
  ① **不画卡片描边**——窗口只有 420px 宽，再切一刀更挤；分界全靠组标题 + 18px
  组间距 + 组内 1px 细线（`_section()` / `_divider()` / `_row()` / `_stacked_row()`
  四个积木，见 `ui/settings_view.py`）；
  ② **说明只给「不解释就不敢动」的项**（去重范围、删除策略、敏感策略、5 个滚动
  开关…），主题/字体大小这类自明的保持单行——每行都挂小字会让页面长一倍、一半是
  废话；tooltip 全部保留；
  ③ **标题不加粗**——满页加粗正是「后台管理系统」那种重量感的来源，层级靠位置和
  组标题，不靠字重。
  分组按**用户任务**排：外观 → 历史与存储 → 隐私 → 系统 → 关于（清理数据归在
  「历史与存储」——它删的就是存储的数据；「关于」压成一行，不再占三行）。
  `_load_from_config` / `_collect_overrides` / `_on_change` / 全部信号连接都按
  **控件引用**走，所以这是**纯布局重构**：控件属性名一个没变，测试不受影响。
  回归用例 `test_settings_page_layout_grouped_no_horizontal_scroll`（分组标题 +
  关键控件齐全 + **长说明不许撑出横向条**）。
- **交互约定：能自动就别让用户多点一下**（全项目统一）。设置页是**改动即生效**
  （无「保存」按钮，见 §14）；清理数据弹窗是**改动即刷新**（无「查询」按钮，
  时间/类型/会话任一变化自动重查）。
  ⚠️ 自动刷新要配**防抖**：清理弹窗的 `list_older_than` **没有 LIMIT**，
  「全部历史」在 5000 行的库上实测单次 ~170ms（SQL+构造 44ms + 重建整张预览表），
  连拨几个下拉不防抖就是连着卡几次；`_REFRESH_DEBOUNCE_MS = 150`（单次改动仍
  像立刻生效，连拨只查最后一次）。回归用例
  `test_clean_data_dialog_filters_auto_refresh`（无查询按钮 + 改下拉即更新 +
  连拨 3 次只查 1 次）。
- **模板页两栏卡片 + 编辑弹窗**（`templates_view.py` +
  `ui/template_components.py`）：左分类（source-list 计数右对齐）/ 中列表
  （搜索 + 两行卡片行：名称+★ 行尾 ★ 点击区=收藏切换，shortcut 钥匙片 +
  触发方式）。**编辑器 TemplateEditorDialog 不常驻**——点击模板行/新建时
  弹出（保存/删除成功 accept → 视图 reload），页面整体更窄。弹窗内：
  名称 Shortcut 分类 触发方式分段控件 变量 Tag Pygments 高亮代码编辑器
  保存/删除/取消。组件化：TemplateCardDelegate / FolderSourceDelegate /
  VariableTagBar / TemplateHighlighter（CodeHighlighter 子类：{{变量}}
  accent 覆盖在 Pygments 之上）
- **变量区（v7）**：胶囊条只显**常用变量**（config `template.favorite_variables`，
  null=全部预设；「变量库」★ 管理）+「变量库」悬停弹层（全部变量按来源类别
  分组、每行 ★ 切换常用、点击插入，鼠标在按钮/弹层上都保持打开）；「＋ 新增」
  自定义变量进 `extra_variables` **并默认进常用**；内容编辑器输入 `{{` 弹变量
  自动补全（注册表内置+自定义，常用在前）
- **调色板取色**：自绘 delegate 用 `option.palette`（accent 走 Link 角色，
  深浅主题自适应）；**QImage.constBits() 是 BGRA 字节序**——像素分析
  脚本按 RGBA 读会 R/B 反转（调试血泪）
- **图片行缩略图：等比、不压扁、开抗锯齿**（2026-09-30，用户报「缩略图看不清」）。
  缩略图框 **高固定 68px**（`THUMB_SIZE_BASE`，行高不变——用户确认档位），
  **宽度按原图比例**、上限 2.5×68=170px（`_THUMB_ASPECT`，21:9 也装得下）；
  用 `QPixmap.scaled(..., KeepAspectRatio)` 缩到框内，**不是**塞进 68×68 方框
  ——后者把宽图压成方图，横竖都糊。再开 `SmoothPixmapTransform` 抗锯齿降采样
  （512→136 这种大幅缩小不开就是锯齿一片）。源缩略图提到 512px（§3.5）也是为配
  Retina 下 340 物理 px 的需求
- **滚动观感 = 原生顺滑**（用户确认档位：不做回弹、不做夸张惯性滑行）。
  按输入设备分流，这是唯一可靠判据 `QWheelEvent.phase()`：
  **触控板**（带 Begin/Update/Momentum/End）——系统自带惯性曲线，我们**只按
  倍率缩放距离、不补动画**（自己再叠时间轴会和系统惯性抢方向盘）；
  **鼠标滚轮**（`NoScrollPhase`）——Qt 原生无任何缓动，由
  `ui.animations.SmoothWheelScroller` 补一层 OutCubic 减速（140–320ms）。
  两者的距离都照抄 Qt 的 `(angleDelta/120) × wheelScrollLines × singleStep`
  （不另拍步长），再乘**滚动速度倍率**（设置页「滚动速度」→ `app.scroll_speed`；
  1.0 = 原生，默认 0.5——Qt 会再乘 `wheelScrollLines` 行，macOS 上偏快）。
  ⚠️ 实测（2026-09-30 离屏探针）`QListView`/`QScrollArea`/`QPlainTextEdit`/
  `QTextEdit` **一律只看 `angleDelta`，`pixelDelta` 被完全忽略**——「像素模式让
  pixelDelta 生效」是错的，`ScrollPerPixel` 只解决**定位**精度（别量化成整行），
  距离始终由 `angleDelta` 决定。接入一行：
  `enable_smooth_wheel(任意 QAbstractScrollArea)`。
  与自带手势机的页面（历史页横滑切类型、模板页横滑平移）同装 viewport 时，
  **手势过滤器必须后装**——Qt 的多个 eventFilter 是「后装的先跑」，手势机要先
  看到原始事件才锁得住纵向；否则缩放层先吃掉纵向事件（`_dy_sum` 恒为 0），
  滚动末尾的手抖又会误切类型。系统「减少动效」开启时完全不介入，退回原生瞬时
  （§9 两条坑）
- **列表逐项入场 = 只播首次填充的瀑布**（历史页，对齐 iOS / Flutter
  AnimatedList 默认观感）：行从下方 64px 滑入 + 透明度 0→1，单行 300ms
  OutCubic；相邻行按下标错峰 50ms、末行延迟封顶 500ms（整段 ≤800ms，与行数
  无关），已露过面的行不重播。**错峰基准是「本轮首个绘制的可见行」（视口顶行），
  不是行号 0**（2026-09-30 回归，用户实测报「滚动条停在中间时切视图先白屏半秒
  再出数据」）：模型重建只改 range 不改 value，滚动位置被保留，可见行都在 30 号
  开外，按绝对行号算会**全部撞上 500ms 封顶** → 整屏 alpha=0 白等半秒。
  **滚动一律不动画**（关键取舍，别再加回来）：
  滚动时几乎每一行都是「初次露面」，逐条播就是让**整个视口常驻中间态**——实测
  连续滚动时 100% 的可见行 `alpha < 0.9`（中位仅 0.37）、位移中位 15px，读起来
  就是「帧率低、不丝滑」（用户实测报的正是这个）。同一轮实测里 delegate 单帧
  绘制只要 ~2.3ms（p95 2.8ms、零次超 16.7ms 预算），**根本不是帧率问题**，
  是常驻半透明。故 `observe` 只在**首次填充尚未结束**时为可见行排队，用户一
  滚动（**真实滚轮/按键输入**，不是 `valueChanged`——见 §9）瀑布立即收摊——否则装载后 800ms 内
  滚到的行会按 `MAX_DELAY_MS` 排队，位移一整行高、alpha 0，**隐身半秒**。
  **只维护 `{行号: 起始时刻}` 一张表 + 一个 16ms QTimer**
  （`ui.animations.ListEnterAnimator`），每行进度按单调时钟现算，偏移/透明度由
  `HistoryDelegate.paint` 应用——上千项也不建 per-item 动画对象、不用
  QGraphicsEffect。**入场由绘制驱动**：delegate 在 paint 顶部上报可见
  （`_note_visible` → `observe`），故「首次可见」与「首次绘制」等价，滚动/改尺寸
  /重排都不用接信号。整表填充的播放点在 `_apply_type_filter`（唯一汇合处）；
  `add_item` 单条插入**不播**（`rows_inserted` 把新行记为已就位）。静止态
  delegate 走原路径（`_enter_fx` 返回 None），收尾帧与无动画逐像素一致
- **切页不重做已经做过的事**（2026-09-30，用户报「快速在几个视图之间切换能感受到
  卡顿／数据加载较慢」）。根因是每次进入页面都完整做一遍「查库 + 重建 + 重播动画 +
  整页淡入」，四个都要治：
  ① **数据修订号**（`app/events.py`，模块级 `bump()/revision()`，**不引入 Qt 信号**）
  ——挂在 SQLAlchemy 的 `engine "commit"` 事件上（`database/engine.py`），
  任何提交都算「数据变了」，只读查询不算。四个页面 `showEvent` 改成
  `if self._loaded_rev != events.revision(): self.reload()`，装载**之后**再记，
  免得漏掉装载过程中的提交。挂 commit 事件而非散在各写入点，是为了**漏不掉写路径**；
  失败方向也是保守的（多查一次）。切页的 4-5ms 同步查库由此变成「几乎不查」
  ② **内容指纹**：`set_items` 先算 `[(id,type,preview,content,file_path,pinned,
  favorite,session_name,language,sensitive,expires_at)…]`（**别用 `(id,pinned,
  favorite)` 三元组**——测试里构造的条目 `id` 默认 0 会撞键，实测动画被误跳过），
  与上次相同则 `_apply_type_filter(animate=False)`——模型照旧重建（0.53ms），
  但**不重播 800ms 瀑布**。用户真的点类型 tab 时仍 `animate=True`
  ③ **淡入节流**：`_fade_in_page` 距上次切页 <250ms 直接显示不淡入
  （每次淡入是 140ms 整页离屏渲染，连点会一段没走完就叠下一段；中途重启的淡入
  读起来就是闪）
  ④ 顺带把 delegate 的 `_pixmap_cache` 从无界 dict 改成 `OrderedDict` LRU（上限
  256）——一张 256×192 的 QPixmap ≈ 196KB，长会话/多会话切换会累积到上百 MB
- **滚动视觉装饰**（`ui/scroll_fx.py`，2026-09-30，用户要「更多视觉装饰」）。
  五件套由 `enable_scroll_fx(area, delegate=None)` 装配，**逐项可开关**（设置页
  「滚动效果」→ `app.scroll_effects`，键名与 `_EFFECTS` 一致）：
  ① **悬浮滚动条**（`OverlayScrollBar`）——原生条 QSS 上样式后变占位（吃 10px
  布局宽，见 §9），故设 `ScrollBarAlwaysOff` + 自绘一条**浮在内容上方**的细条，
  滚动时淡入、闲置 ~0.9s 淡出、可直接拖拽；完全透明时置
  `WA_TransparentForMouseEvents`（否则右侧 10px 的条目永远点不到）。内容区因此
  宽 10px ② **上下边缘渐隐**（`EdgeFade`）——只在**还有内容**的那一侧盖「列表
  底色 → 透明」的渐变，高度随离端点距离增长（滚到端点自然收成 0）③ **缩略图
  视差**（`ScrollFx.parallax_for`，±6px，delegate 画缩略图时读）④ **卡片抬升**
  （`ScrollFx.lift()` + delegate `_draw_lift`：四层同心圆角矩形叠出近高斯阴影，
  比 QGraphicsDropShadowEffect 便宜两个数量级）⑤ **卡片景深**
  （`ScrollFx.depth_for()`，2026-10-09 移植自仓库根的 `demo_v.py`，**按用户要求
  改了两处**）：把卡片**缩放 + 向下推 + 向列表底色淡出**，但**只作用于视口中心
  以下**（顶部不要这个效果），且**只在往下翻列表时出现**（往回翻或停下 → 0，见
  `_down_gate`）。⚠️ 闸门是**方向闩锁**（只看滚动方向，不看速度大小），
  别改回按速度算——那会让下半屏随每段甩动的惯性衰减「呼吸」，见 §9。
  **3/4/5 都只在滚动进行中非零**：滚动后为 1.0、停手后衰减到 0，所以静止时 delegate
  一律走**与无装饰逐像素相同**的绘制路径。⚠️ **收尾时间 ⑤ 比 3/4 快一倍**：
  3/4 用 `_HOLD_MS` + `_DECAY_MS` = 90 + 240 = **330ms**；⑤ 用**自己**的
  `_DEPTH_HOLD_MS` + `_DEPTH_DECAY_MS` = 45 + 120 = **165ms**（用户实测「停下之后
  缩回去等得有点久」，要求「恢复时间减半」）。为什么只有 ⑤ 要快：三个通道里只有它
  **看得出来**——缩放 + 变淡有静止参照物（卡片自己的边界），而阴影淡出、缩略图滑回
  6px 都几乎看不见，同一段余韵只有 ⑤ 读起来是「慢」。⑤ 的收尾强度是**独立状态**
  `_depth_activity`（`_down_gate()` 乘它，**不再**乘 `activity()`），两条曲线只在
  `_mark_active()` 里一起复位到 1.0。⑤ 还多一个方向条件。⑤ 开着时 ③ 自动让位
  （`parallax_for` 恒返回 0）——两者是同一个想法的弱化版与完整版，一起上会把缩略图
  推两次。
  **为什么 ⑤ 能被看见，而 ③ 不能**（关键）：⑤ 改的是**面积和明暗**（最多缩 12%、
  淡出 α46），③ 只改位移（±6px）且**视口正中恒为 0**——而人眼正盯着中央那几行。
  连续平滑的位移没有静止参照物，读不出来；缩放有卡片自己的边界当参照物。
  3/4/5 的绘制留在 delegate（要知道行矩形与 `_s` 缩放），`scroll_fx` 只提供
  `activity()`/`lift()`/`parallax_for()`/`depth_for()`。
  ⚠️ **delegate 取强度必须走各自的 `lift()` / `parallax_for()` / `depth_for()`，
  别读 `activity()`**——`activity` 只由「三项任一开着」驱动，只开视差时它照样是
  1.0，直接读它会让「卡片抬升」勾选框完全失效（用户实测报的「开关不明显」）。
  ⚠️ **⑤ 的两条硬约束别改回去**（用户明确要求，有回归用例钉着）：只在**下半屏**、
  只在**往下翻**。demo 原版是「上下对称 + 常驻」，我们这两处是刻意偏离。
  系统「减少动效」开启时 3/4/5 整体关掉（悬浮条与渐隐是静态装饰，保留）
- **装饰的静止判据要连淡出一起等**（`ScrollFx._tick`，实测踩坑）：activity 比
  滚动条先归零（330ms vs 900ms idle + 300ms 淡出），只判 activity 会在浮层条
  还是 1.0 时就停表，**条卡在画面上不消失**。判据须含
  `idle_ms >= _BAR_IDLE_MS and bar_alpha == 0.0`
- **调色板颜色串不能直接喂 QColor**（`scroll_fx.parse_color`，§9）：调色板里半透明
  项是 `"rgba(0, 0, 0, 0.22)"` 这种 QSS 函数串，`QColor` 构造出来是无效色；8 位
  十六进制又是 AARRGGBB（alpha 在前），当 RRGGBB 用会串位。自绘控件取
  `scrollbar` 这类项必须自己解一次（解不出退回兜底色，**绝不返回无效色**——那是黑块）

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
   - **`datas` 带上 `resources/scripts`**（发货脚本；与 `resources/icon.png` 同一约定）与 `config`/`actions`
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
    -- v10：渲染/操作会用到的元数据也要快照，不然收藏里的代码条目没有
    -- language → 详情高亮整段无色、敏感条目不知道要遮蔽（用户实测报的）
    language       TEXT,
    source_app     TEXT,
    sensitive      INTEGER DEFAULT 0,
    sensitive_type TEXT,
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
- 迁移：`PRAGMA user_version`（当前 = 6）；v2 快照化、v3 加元数据列、v4 会话用 `PRAGMA table_info` 防重 + ALTER TABLE；**v5 唯一约束 hash → (hash, session_id) 需重建表**（SQLite 无法删约束），保留 id 与全部列 + FTS rebuild（新库 items_fts 未建时跳过）；**v6 模板模块重建 snippets 表**（shortcut UNIQUE）同上模式 + snippet_folders 表
- 文件大小上限：`history.max_file_size_mb`（默认 50MB，0=不限制），on_clipboard_changed 对 FILE 类型 stat 超限跳过
- 会话：`sessions` 表 + `clipboard_items.session_id`（§3.8）；默认会话幂等创建

### 7.3 模板模块（v6，原 Snippet）

- **定位**（文档 §1）：shortcut 触发的本地模板引擎——输入 `pyfunc`+Tab → 解析渲染 `{{date}}/{{time}}/{{datetime}}/{{uuid}}/{{clipboard}}/{{selection}}/{{input:name}}/{{cursor}}` → 模拟 ⌘V 粘贴 → 恢复原剪贴板
- **分层**（§83-89）：`services/template/`（errors/token/parser/variables/renderer/matcher/registry/custom_vars/value_sources/ax_text）+ `template_service.py`（CRUD/文件夹/搜索评分排序）+ `insertion.py`（粘贴模拟）
- **变量系统（v7，唯一事实源 = `services/template/registry.py`）**：
  - `VariableMeta`：`insert`/`category`/`description`/`usage`/`example`/`keyword`/`value_source`/`builtin`。内置 8 个变量（date/time/datetime/uuid/clipboard/**selection**/input/cursor），description/usage/example **必填**（悬停 tooltip 三行组装）
  - **值源分类**（`VariableMeta.value_source`，**只读元数据**、不参与求值分发）：`系统状态`（OS 给的：date/uuid/clipboard/selection）、`用户输入`（弹窗问：input）、`上下文标记`（插入位置：cursor）、`外部计算`（命令/脚本——**内置变量无实例**，仅登记分类，`SRC_EXTERNAL` 当前零引用）。自定义变量的值来源走**另一套**运行时注册表 `SOURCE_*`（见下）
  - **默认日期格式（config 接线，2026-09）**：`config template.date_format/time_format/datetime_format`（**strftime** 串，defaults.yaml:45-47）作 `{{date}}`/`{{time}}`/`{{datetime}}` **无参数**时的全局默认；带参数（`{{date:YYYY年MM月}}`，模板格式）逐次覆盖；config 缺键/空白 → 回落内置默认。三级取值在 `DateTimeProvider.render`（参数 > `ctx.date_formats` > `_DEFAULT_FORMATS`），config 值**不过 `map_format`**（否则用户的 `%a`/`%p` 会被「模板格式」规则改写）。这三个键此前是**死配置**（defaults.yaml 有、全仓无人读，硬编码生效）
  - **消费者**：parser 合法性校验（`_KNOWN` ← registry.names()）、胶囊悬停 tooltip、`{{` 自动补全候选（`filter_candidates`：常用在前、其余按类别）、「变量库」弹层分组（`group_by_category`：系统→用户输入→上下文→自定义）、常用变量持久化（config `template.favorite_variables`，null=全部预设）
  - **重复 input 自动编号**：`next_input_insert`——模板已含 `{{input:name}}` 再插入同名 → `{{input:name2}}`/`{{input:name3}}`（每次独立输入，避免去重只问一次）；胶囊点击与自动补全 accept 都走此规则
  - **自定义变量值来源（v8）**：`extra_variables` 由 `list[str]` 迁为结构化 `{name, description, source, config}`（`services/template/custom_vars.py` 读写 + 旧格式自动迁移，剥 `{{}}`、默认 input 来源）。四种来源（`registry.SOURCE_*`）：
    - `input`：触发时弹窗询问（值在 `ctx.input_values[name]`；与 `{{input:name}}` 共享同名去重键——模板里 `{{name}}` 与 `{{input:name}}` 视为同一个输入，只问一次）
    - `fixed`：`config.text` 原样插入（严格固定，不做替换）
    - `command`：`config.command` 经 `/bin/sh -c` **同步执行**，`stdout.strip()` 作结果。失败（空命令 / 非零退出 / 超时 / 异常）按 **`config.on_error`** 处理：`empty` 留空（默认 = 旧行为）/ `text` 插 `config.on_error_text`（缺省 `[变量取值失败]`）/ `cancel` 抛 `VariableValueError` → **整次插入放弃**（半句话插进正文比什么都不插更糟）。失败一律**记日志（含 stderr，截断 300 字）+ 走可见通道**（`value_sources.set_error_reporter` 注入，bootstrap 接托盘通知）——此前 stderr 被 `capture_output` 收走却从不记录、失败只剩空串，用户分不清「功能坏了」还是「脚本写错了」。超时 `config.timeout` 秒（夹到 1–60，默认 5）
    - `state`：`config.state`（v1 仅 `frontmost_app` 前台应用名），框架预留更多系统状态
    - **命令值源的三个上下文通道（2026-09 加）**：脚本据此「知道现在是什么情况」，不必自己去猜/去重新读系统状态。`CommandValueSource.render` 把 `RenderContext` 翻译成三样东西一起喂给 `run_command`：
      - **环境变量 `CW_*`**（`build_command_env`，在 `os.environ` 上**叠加**——脚本仍该能用自己的 PATH/HOME）：`CW_VAR` 变量名 / `CW_TEMPLATE` 模板原文 / `CW_CLIPBOARD` 剪贴板 / `CW_SELECTION` 选中文本 / `CW_APP` 目标应用名 / `CW_NOW` 触发时间（ISO 8601）/ `CW_ARGS` 参数原文 / `CW_INPUT_<名>` 每个输入变量的值（名大写，如 `{{input:who}}` → `CW_INPUT_WHO`）。表在 `value_sources.ENV_HELP`（编辑器提示与文档共用一份事实源）
      - **stdin = 选中文本，无选中则剪贴板**（`stdin_for`）——「把选中的东西交给脚本处理」的最短路径：脚本 `cat` 就读到了。**恒以管道喂入（默认空串），不继承本进程 stdin**——否则脚本里一个 `cat` 会挂在终端上等输入、把触发链路整个卡住
      - **`$1..$@` = 模板里 `{{变量:参数}}` 的参数**（`split_args`，shlex 按 shell 习惯切分：`{{sum:1 2}}` → `$1=1 $2=2`，`{{say:"你好 世界"}}` → `$1=你好 世界`；引号不成对不报错、整串当一个参数）。经 `sh -c 'cmd' cw arg1 arg2…` 传入——`$0` 用占位名 `cw`，否则第一个参数会跑到 `$0` 上、脚本里 `$1` 恒为空
      - `CW_APP` 必须由**调用方在触发瞬间捕获**（`bootstrap._render_and_insert_impl` 传 `app_name=`）：picker 流程弹层/对话框已把前台让给本应用，此时脚本自读 `frontmostApplication()` 拿到的是我们自己（与 §触发 那段同源根因）
    - **脚本通道 `cw:<脚本名>`（2026-09 加，见 §7.4）**：`config.command` 写成 `cw:upper` 即「跑脚本目录里那个文件」，不必再手写绝对路径 + 自己挑解释器。用户目录 `config/scripts/` 优先，同名覆盖内置 `resources/scripts/`。脚本**参数写在模板里**（`{{upper:x}}` → `$1`），不写在命令串里——`cw:extract url` 这种写法会被显式拦下并报「参数请写在模板里」（否则参数静默丢失，正是最难查的那类坑）
    - 值源 provider 注册表 `services/template/value_sources.py`：新增值源 = 加一个 `ValueSourceProvider` 子类 + `build_value_sources()` 登记一行；`command` 来源本身即「脚本扩展」通道（不写 Python 也能接任意命令）。语义：`{{name}}` = 自定义变量直接求值；`{{input:name}}` = 临时输入，**§43 旧配对已移除（彻底解耦）**
  - **自定义变量编辑**：`VariableEditDialog`（变量名/描述/值来源下拉/配置区按来源切换）；`command` 来源的编辑区是**多行框**（`QPlainTextEdit`，多步脚本/pipeline 写得下）+ **「试运行」**（`run_command` 同一条执行路径、同一超时，就地显示 stdout / 退出码 / stderr / 耗时；不套 `on_error`——作者要看真实退出码而非被策略替换的兜底文案）；右键胶囊弹菜单（编辑/删除）；**改名扫描模板引用并警告但不自动替换**（避免静默改坏历史模板）
  - **每次触发只渲染一次（2026-09 修）**：`TemplateService.collect_inputs_for(content)` 纯解析收集输入，替代触发链路原先的「先渲染一遍只为拿 input_requests、拿到用户输入后再渲染第二遍」。渲染有副作用——`command` 值源会真执行外部命令，双渲染使其**每次触发执行两遍**（`echo x >> f`、`say`、随机类脚本结果随之出错）。input_requests 只依赖 token 流，与渲染结果无关，故第一次调用不需要渲染；顺带修掉「用户取消输入框时命令已跑过一遍」（现为 0 次）。副作用：含 input 变量时 `{{clipboard}}` 的读取时机从「弹框前」移到「弹框后」（用户若在弹框期间复制，取到的是新值；不复制则无差别）
  - **自定义变量的 `:params` 接上了（2026-09 修）**：`parse` 命中自定义变量时同时保留 `params`（查表键 = 变量名）与 `args`（新增 `Token.args`），`CustomProvider` 把 `token.args` 透传给值源 → **命令来源的参数成为脚本的 `$1..$@`**（见上条「三个上下文通道」）。此前参数在解析期就无声消失（既是数据丢失，也让「脚本传参」这个通道无从做起）。其余来源（input/fixed/state）写了参数无处可用 → 保存期由 `parser.validate_args` 挡下并给出消息（`validate_template(..., custom_vars=)` / `create_template` / `update_template` 都走它）
  - **已知缺口（2026-09 逐条核对代码后记录，均未实现）**：
    - **`{{cursor}}` 位置产出即被丢弃**：renderer 正确返回 `cursor_pos`，但 `bootstrap._render_and_insert_impl` 两处渲染都接 `text, _, _ = …` → 插入后光标恒在末尾（与下方「插入」行「第一阶段不定位」一致，仍是现状）
    - `state` 值源只有 `frontmost_app` 一个状态；`command` 值源**同步跑在触发链路上**（超时默认 5s / 可配 1–60s，期间 UI 不响应；且此时焦点已还给目标应用 → 超时表现为目标应用卡住后才出现文本）
    - **内置变量的参数静默丢弃**：`{{uuid:x}}`/`{{clipboard:x}}`/`{{selection:x}}`/`{{cursor:x}}` 的 params 在 `parse` 里根本没保留（自定义变量那条已修，内置这条未改——它们本就不接受参数，但也没有保存期提示）
    - **命令值源 cwd 固定为应用启动目录**（脚本通道除外——`cw:` 跑脚本时 cwd = 脚本所在目录，见 §7.4）
    - **`jq` 这类外部工具仍无 PATH 保障**：`build_command_env` 只**追加**缺失的标准目录（`/usr/local/bin`、`/opt/homebrew/bin`、`/usr/bin`、`/bin`、`/usr/sbin`、`/sbin`，`ensure_path`，不前置、不改动已有条目的优先级），因此 launchd 启动的实例至少能看到系统与 homebrew 的二进制。但**非标准前缀（用户机器上 `jq` 在 `/opt/anaconda3/bin`）仍看不到**——所以发货脚本一律只用 Python 标准库、用应用自己的解释器跑（§7.4），不依赖 PATH 里有什么。`services/autostart.py` 的 plist 依旧不设 `EnvironmentVariables`
    - **高级语法全无**：默认值/回退（`{{x|默认}}`）、select 枚举、过滤器管道、日期偏移（`{{date:+1d}}`）、字面量转义（`\{\{`）。结构上受限于 `_VAR_RE = \{\{(\w+)(?::([^}]*))?\}\}`——只支持「一个 `\w+` + 一段不含 `}` 的 params」，params 目前三种语义：日期格式 / input 标签 / 自定义变量参数（`{{name:参数}}` → 脚本 `$1..`）
    - 内置变量没有「外部计算」值源（`SRC_EXTERNAL` 零引用）；`VariableMeta.value_source` 无代码读取（纯文档元数据，见上）
- **数据**：snippets 表（shortcut UNIQUE/folder_id/enabled/favorite/trigger_mode/usage_count/last_used_at）+ snippet_folders；旧数据迁移 shortcut=name 小写（冲突加 `_<id>`）；默认文件夹（个人/工作/开发/模板）+ 默认模板（shrug/today/uuid/quote）幂等插入；**v9 撤回 v8 种入的 17 个发货变换模板**（形态不成立，见 §7.4）——只删 name/shortcut/content 三项都与当初一致的行（用户改过任何一个字就留下），文件夹清空才删
- **触发**（§7）：HotkeyManager 扩展 `raw_key_down` 信号转发无 ⌘⌃⌥ 修饰的按键（字符用 `CGEventKeyboardGetUnicodeString` 跟随布局，回退 vk 映射表），事件透传不消费；matcher 主线程维护输入缓冲，tab 模式 Tab 触发 / automatic 模式输完立即触发，匹配从缓冲末尾扫最长后缀
  - **输入法策略（用户要求：无论哪种输入法，必须完整 shortcut 彻底输入文本框后才触发）**：
    - **英文输入法**：无组合，按键即上屏 → 输完最后一个字符**延迟确认**触发：命中后挂起 pending（缓冲快照），**200ms 内缓冲变化（还在输更长的词，如 signature 的 sig）取消；词边界键（空格/标点 = 词完整）或 200ms 超时确认触发**——防 prefix 误触（用户实测：想打 signature，输到 sig 就被替换）
    - **中文输入法**（`is_chinese_ime()`，TIS/ctypes 检测输入源 ID，不依赖被聚焦应用）：所有字母都进输入法组合、未上屏，按键路径**完全不碰文本**（碰了会破坏组合，实测 sig→siv）；**提交键**（空格/回车/标点，输入法正在提交组合）keyDown 时触发——事件顺序保证 ⌥⌫ 落在已提交文本上；Tab 触发由插入层 **Escape 取消组合** + 粘贴（`cancel_ime=True`，不能 ⌥⌫）
    - **自动纠正免疫**：缓冲记录的是用户按下的原始键（sig），不管输入法界面显示 siv，触发替换以实际输入为准，⌥⌫ 整词删除
    - **焦点文本轮询固定 `skip_ascii=True`（只匹配中文 shortcut）**：英文 shortcut 由按键路径覆盖（英文延迟确认 / 中文提交键）——轮询里英文 shortcut 有两个问题：组合中 AX 值可能含未上屏拼音（部分应用读不到 marked range）会提前触发（用户实测：uuid 未按回车就触发）；且英文 shortcut 有 prefix 误触风险。中文 shortcut 组合中显示的是拼音，天然不会误匹配
  - **TIS 实现坑**：符号在 **HIToolbox**（`Carbon.framework/Versions/A/Frameworks/HIToolbox.framework/Versions/A/HIToolbox`），ApplicationServices umbrella 不导出；加载 Carbon 主二进制是 stub 会崩（曾经的坑）；CFString* 符号单独从 CoreFoundation 加载
  - **AX 路径（补充，非主路）**：`is_ime_composing()` 读焦点元素 `AXTextInputMarkedRange`（length>0 = 组合中）+ 焦点文本轮询（400ms）匹配已提交文本——只对 AX 健全的应用有效（TextEdit/Notes 等）；**VS Code/Electron 的 AX 树没有任何文本元素，焦点元素读取返回 kAXErrorNoValue，AX 方案在那里整体不可用**（见 §9 坑速查）
  - **焦点文本轮询**：`mode="automatic"`（**不是 "all"**——"all" 会让 tab 模式模板在英文输入法下被随便输入触发，破坏防误触语义）；组合中跳过且不更新缓存（否则组合文本被缓存，上屏后文本未变永不触发）
- **插入**（§70-72）：保存原剪贴板 → `watcher.set_paused(True)`（临时内容不进历史）→ 写入 → CGEventPost ⌘V → 恢复 → 恢复监听；`{{cursor}}` 第一阶段不定位（光标停末尾）
- **Picker**（§16）：⌘⇧S 全局弹窗（搜索排序：shortcut 精确>name 精确>shortcut 前缀>name 前缀>content>最近使用）
- **兼容**：`snippet_service.py` 代理到 TemplateService（旧 `render_snippet` 保留：未知变量原样保留不抛错）

### 7.4 脚本通道（`cw:` 值源）

**目标**：让「一段文本进来 → 处理过的东西出去」这类玩法靠**内容**扩展，不必改代码——用户往脚本目录里丢一个文件，就多一个模板变量。

> **⚠️ 2026-09-20：随应用发货的 17 个「变换」模板已整批撤回（v9 迁移）。**
>
> 它们当初这么设计：「选中一段文本 → ⌘⇧S → 选「转大写」→ 回车 → 变了」。
> 但触发靠**打字**，而打字的第一个字母就把要变换的选中文本覆盖掉了——
> **输入从来拿不到**（`{{selection}}` 读空 → `stdin_for` 退回剪贴板；用户
> 实际体验是「选中文本 → 输 `lu` → Tab → 什么都没提取出来」）。
>
> 换触发方式也救不了：抢在按键送达目标应用之前用 AX 读一次选中文本
> 技术上可行（事件 tap 是 `kCGHeadInsertEventTap`，回调早于事件送达），
> 但那只是让一个**不合理的交互勉强跑通**——而且结果又插回原处、原文没了，
> **没法对照验证**。用户已经指出更根本的一点：内容本来就在文本框/剪贴板
> 里，复制一下就行，多这一步是绕路。
>
> 结论：这批模板**形态不成立**。「打字展开」（打一个词、它变成别的字，如
> `shrug<Tab>` → ¯\\_(ツ)_/¯）与「内容变换」（输入在别处、输出是它的派生）
> 是两类东西，**不该共用一条触发通道**——前者没有「外部输入」这个概念。
> 变换类以后重做成「对剪贴板条目执行，结果回剪贴板」（原文不动，可对照）。
>
> **脚本本身保留**：它们正是将来那条路的引擎，`cw:` 求值通道完全不变。

**两个目录**（`services/template/scripts.py`，**用户优先 → 同名覆盖内置**）：

| 目录 | 归属 | 用途 |
|---|---|---|
| `config/scripts/` | 用户可写 | drop-in：丢个文件进去就多一个 `{{文件名}}` 变量，无需任何设置页 |
| `resources/scripts/` | 随应用发货、只读 | 内置变换；随版本更新 |

**脚本 = 模板变量（按合并，不按配置）**：`script_variables()` 把每个脚本合成一个 `CustomVariable(name=文件名, source="command", config={"command": "cw:<名>"})`；`load_custom_vars()` = 脚本变量打底，用户的 `extra_variables` 按名覆盖。**零改动** parser/renderer/引擎——`CustomProvider` 本来就读 `ctx.custom_vars` 并按 `var.source` 分发。

**脚本变量在界面上怎么出现**：进**变量库**（`CAT_SCRIPT`「脚本」分组，排在「上下文」与「自定义」之间）、进**模板编辑器的 `{{` 自动补全**、进**胶囊区**（★ 过才进）。三条都由 `services/template/custom_vars.py::visible_script_variables()` 供数——它只给「没被同名用户变量顶掉」的脚本变量，因为**展示与求值必须是同一份真相**：否则库里会出现两条同名行，其中一条点了根本没效果。库里脚本行的描述取自脚本头部的 `# cw:` 自述，悬停说明由 `registry.custom_tooltip()` 生成，值来源写「**脚本**」而不是「外部命令」——`cw:upper` 不是命令，写成「命令」用户会去别处找一个叫 `cw` 的命令。

**哪些文件算脚本**：后缀白名单 `(.py, .sh, "")`，且排除 `.`/`_` 开头的名字 —— 这样脚本可以带同目录的数据文件（`data.txt`）与被 import 的辅助模块（`_common.py`），不会被误注册成变量。

**脚本自述元数据**（扫文件开头 5 行，避免读整个大脚本）：

```
# cw: 一句话说明          → 变量描述 / 模板 tooltip / 错误提示里的可用清单
# cw-timeout: 10         → 覆盖命令默认超时（活数据脚本要联网，5s 不够）
```

**解释器与执行**：

- `.py` → **应用自己的解释器**（`sys.executable`，venv python，依赖齐全）；其余（含 `.sh`、无后缀）→ `/bin/sh`
- 打包版（PyInstaller）`sys.executable` 是应用二进制、**不能**执行 `.py` → 退到系统 python3（`/usr/bin/python3` → `/opt/homebrew/bin/python3` → `/usr/local/bin/python3` → `which python3`）。本机 `/usr/bin/python3` 是 **3.9.6**，因此**发货脚本只用标准库、且必须 3.9 兼容**（不用 `match`、不在会被求值的位置用 `X | Y` 注解）
- **cwd = 脚本所在目录** → 脚本可以带同目录数据文件一起发货，也能 `open("data.txt")`
- **`CW_SCRIPT_DIR`**（`os.pathsep` 分隔，用户目录在前）= 脚本互调的入口
- **参数**：`{{名:甲 乙}}` → `sys.argv[1:]` = `["甲","乙"]`（比 `sh -c` 少一层，没有 `$0` 占位问题）
- 环境变量、stdin（选中文本）等上下文通道与命令值源共用，见 §7.3

**坑（已踩）**：

- **`PYTHONDONTWRITEBYTECODE=1` 必须设**（`script_env()`）：cwd = 发货目录时 Python 会往里写 `__pycache__/`，打包版那是只读的
- **脚本名不能与标准库同名**：`sys.path[0]` = 脚本目录 → 叫 `csv.py` 的脚本 `import csv` 会导入**它自己**，整个脚本崩在 import 上。故内置的是 `csv_table.py`。`tests/test_shipped_scripts.py::test_shipped_scripts_avoid_stdlib_name_shadowing` 用 `importlib.util.find_spec` 拦住这类命名
- **AppleScript 术语是「按 App + 编译期」的**：`name of current track` 在 App 没装时**编译不过**（`-2741`），而 `try` 抓不住编译错误。`now_playing.py` 先用只用基础术语的 `application "X" is running` 探测，只对**正在运行**的 App 编译那段脚本
- **参数写进命令串会被拦**：`cw:extract url` 报「参数请写在模板里 `{{变量名:参数}}`」，不静默丢参数

**打包**：spec 的 `datas` 必须含 `("../resources/scripts", "resources/scripts")`（与 `resources/icon.png` 同一约定）。漏了这行 → 打包版里写 `{{脚本名}}` 的模板全部 `UnknownVariableError`，变量库里也没有这些脚本变量。

**回归测试**：`tests/test_scripts.py`（解析/优先级/执行/注入/元数据）、`tests/test_shipped_scripts.py`（**发货脚本内容也是要防回归的代码**：24 条 `parametrize` 走真实 `parse`→`render`→`cw:` 链路）、`tests/test_services_v1.py::test_migration_v9_*`（撤回/幂等/不删用户改过的行）、`tests/test_variables_ux.py::test_variable_library_lists_script_variables`（变量库「脚本」分组 + 描述）、`tests/test_ui.py::test_editor_dialog_variable_library_scripts`（弹窗一打开变量库与补全里就有脚本变量）。

**已知缺口（未实现）**：`resources/scripts/` 若丢失而用户的模板仍写 `{{upper}}` → 渲染抛 `UnknownVariableError`（走失败通道，不静默）；脚本目录无 UI 管理（要加脚本就手动放文件）；**变换类玩法整体未落地**——「对剪贴板条目执行 + 结果回剪贴板」还没做，眼下这些脚本只能被用户自己写进模板里用。

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
| 产出 `dist/Clipboard Workspace`（**无 `.app`**，Finder/`open`/LaunchServices 都不认） | PyInstaller **6.x 起 BUNDLE 不再自动补 `.app`**（`osx.py` 把 name 原样拼进 distpath） | spec 里 `BUNDLE(name=APP_NAME + ".app")` 显式带后缀 |
| 深度签名间歇报 `errSecInternalComponent`（同一 bundle **首次必失败、重试即过**，单文件 codesign 却正常） | `--deep` 在 PySide6 万级文件 bundle 上 keychain 争用 | build.sh 对 codesign **重试 3 次**（§6.2） |
| 清理数据把用户原文档删了 | FILE 条目 file_path 指向用户文档，删除无条件 unlink | `is_managed` 守卫只删 images/ 内文件（§3.5） |
| 收藏夹图片粘贴失效 | 删除历史清理了被收藏引用的图片文件 | 删除前查 `is_file_path_referenced`（§3.5） |
| 历史/收藏全部无缩略图，重启恢复 | `@lru_cache` 缓存了失败 None（文件缺失毒化） | 失败抛异常不缓存，`_thumbnail_cached` 只缓存成功（§3.5） |
| 代码详情无高亮 | Pygments 2.x token 是 `_TokenType` 实例，`type(token).__mro__` 取元类链 | 遍历 `token.parent` 链匹配（§3.6） |
| 代码文本压到行号区 | QSS padding 渲染层覆盖 `setViewportMargins` | 行号改独立 gutter 组件（§3.6） |
| 代码首行显示不全 | macOS 透明 QPlainTextEdit viewport 合成异常 | 背景不透明 `$window`（§3.6） |
| 弹窗内容比预期低 8px（「不是从第一行开始」） | macOS 上 Qt.Popup 顶层窗口的 QPropertyAnimation 不被事件循环驱动（pos 动画卡 Running、valueChanged 不发射），`move(y+8)` 初始偏移永久保留 | `fade_in_window` 用 QTimer 强制校正最终位置，不依赖动画信号；复用弹窗先停旧 timer（§6.2） |
| 行号与代码对不齐（数字偏上 ≈3px） | gutter 用 rect 重载顶部对齐画行号，数字 glyph 矮（8.5px vs 文本 14px）；且 QFontMetrics.ascent(11) ≠ QTextLayout 的 OpenType ascent(≈12.7) | 行号用 `drawText(x, y, text)` 基线绘制，基线 = block 顶 + **layout** ascent（§3.6） |
| 弹窗背景透出/首行合成 | Qt.Popup 是 NSPanel 可能走透明合成，`#itemDetail` 无 QSS 背景规则 | `QWidget#itemDetail { background: $window; }` 显式不透明（§3.6） |
| C++ 判成 shell | `#include` 计为 shell 注释、`<int>` 计为重定向 | 预处理器排除 + `(?<![<\w])>` 限定（§3.6） |
| Swift 判成 Python | import+缩进加分过宽 | 缩进加分要求强信号 ≥2（§3.6） |
| md 文档判成 shell | `# 标题` 计为 shell 注释 + 围栏内命令/表格 `|` 反超，平局字典序 shell 靠前 | 标题形行不计 shell 注释；shell 胜出时 md ≥0.80 且 ≥2 种结构信号则按 md（§3.6） |
| 纯文本判成 shell/yaml | shell 0.45 / yaml 0.45 / md 0.4 保底分，零信号也参与竞争 | 零信号一律返回 0.0，不得参与竞争（§3.6） |
| 微信 URL 判成敏感 | 分享链接 token= 查询参数命中 token 正则 | URL 类型跳过敏感检测（§3.7） |
| 复制新文本把置顶挤下去 | add_item 固定插行 0 | 插到置顶组之后（pinned DESC 一致） |
| 会话下拉为空 | 只注入 context 未填充下拉 | bootstrap 装配时显式 `reload_sessions(active_id)`（§3.8） |
| 全局搜索看不到会话来源 | 条目未带 session 名 | `_to_item` LEFT JOIN sessions 填 `session_name`，delegate `_session_tag` 标注（§3.8） |
| 删除会话移回后内容丢失/成孤儿 | INSERT SELECT 同表 id 冲突、session_id 带出原值 | 先取数据再删再插 + 覆盖 session_id=1（§3.8） |
| 新会话复制旧图片被去重吞掉 | 唯一约束 hash 全局去重 | v5 改 (hash, session_id) 联合 + `dedupe_scope` 可配置（§3.8） |
| 右键菜单测试挂起 | 菜单新增「添加到模板」后 `actions()[1]` 索引位移，trigger 到模态对话框 | 测试按文本找动作，不依赖索引（§7.3） |
| 模态 QMessageBox 阻塞测试 | `_warn` 用 QMessageBox.warning（exec 模态） | 测试 patch `_warn` 记录消息（§7.3） |
| CGEventKeyboardGetUnicodeString 返回空 | 只对真实硬件事件有效（构造事件无 unicode 字段） | 回退 vk 映射表（US 布局，§7.3） |
| 默认模板占用 shortcut | 迁移插入 shrug/today/uuid/quote，测试建同名模板撞 UNIQUE | 测试避开默认 shortcut（§7.3） |
| Tab Trigger 误触发（输入法） | CGEventTap 无法读 IME composing 状态 | **已解决**：中文输入法由 `is_chinese_ime()`（TIS）判定——组合未上屏不碰文本，提交键触发；AX marked range 只作 AX 健全应用的补充（§7.3） |
| 组合守卫失效（sig→siv 依旧） | 守卫用 AX marked range，但 VS Code/Electron 的 `kAXFocusedUIElementAttribute` 返回 kAXErrorNoValue、AX 树无文本元素 → `is_ime_composing()` 永远 False | 守卫改用 **TIS 输入法检测**（ctypes + HIToolbox，不依赖被聚焦应用）：中文输入法下按键路径不触发，提交键触发（§7.3） |
| TIS 检测在 pyobjc 里没有 | pyobjc ApplicationServices 只绑定部分 HIServices，TISCopyCurrentKeyboardInputSource 不在 | ctypes 加载 HIToolbox 二进制（`Carbon.framework/.../HIToolbox`），CFString* 从 CoreFoundation 加载（§7.3） |
| AX 路径静默全死 | venv 缺 `pyobjc-framework-ApplicationServices`，`Quartz.kAXValueAttribute` 等常量不存在 → read_focused_text 每次 AttributeError 被 try/except 吞成 None | requirements.txt 显式加 `pyobjc-framework-ApplicationServices`；坑在 pyobjc 的 AX C API 在 HIServices/ApplicationServices 包里，**不在 Quartz**（§7.3） |
| 中文输入法下自动触发把 sig 改写成 siv | 组合中（marked text）收到最后一个字符 keyDown 即触发，⌥⌫ 删除 + 粘贴破坏活动组合，IME 重新提交出乱码；tab 触发没这问题（按 Tab 时早已上屏） | 中文输入法（TIS）下按键路径不触发，**提交键**（空格/回车/标点）触发——⌥⌫ 落在已提交文本上；Tab 触发发 Escape 取消组合（§7.3） |
| tab 模式模板被自动触发（uuid/today 输入即展开） | 焦点文本轮询用 `mode="all"`（无模式过滤），AX 修复后英文输入法下提交的 tab 模式 shortcut 也被匹配 | 轮询改 `mode="automatic"`，只匹配 automatic/boundary；tab 模式走 Tab 键（英文：按键缓冲，中文：Tab 时 AX 末尾匹配）（§7.3） |
| 焦点文本轮询永不触发 | 组合期间把文本（含未上屏组合）写进 `_focused_last` 缓存，上屏后文本未变 → 判"未变化"跳过 | 组合中跳过且**不更新缓存**，上屏后文本变化才能进入匹配（§7.3） |
| 英文输入法打 signature 输到 sig 就触发 | 即时触发在最后一个字符开火，无法区分"完整词"和"更长单词的前缀"（缓冲就是 sig） | 自动触发**延迟确认**：命中挂起 pending（缓冲快照），200ms 内缓冲变化取消，词边界键/超时确认触发（§7.3） |
| 中文输入法 uuid 未按回车就触发 | 焦点文本轮询匹配了组合中未上屏的拼音（部分应用读不到 marked range，`is_ime_composing` 失效） | 轮询固定 `skip_ascii=True` 只匹配中文 shortcut；英文 shortcut 由按键路径（中文提交键）覆盖（§7.3） |
| 触发后 shortcut 残留输入框 | 只粘贴渲染文本，未删除用户输入的 shortcut | matcher 回调携带 delete_count，插入前 `delete_backspaces(n)`（**必须在弹输入框之前**，弹框夺焦后退格打错位置）（§7.3） |
| 文件夹操作按钮不可识别 | ＋/✎/－ 符号按钮：✎ 渲染不出、无文字 | 改文字按钮「＋ 新建文件夹」+ 右键菜单（新建/重命名/删除）（§7.3） |
| 右键变量后整页按钮无反应 | 右键胶囊在 `customContextMenuRequested`（鼠标按下）里同步 `QMenu.exec()` / 弹模态 `QMessageBox`，macOS 上嵌套事件循环残留鼠标 grab，菜单/弹窗关闭后整个编辑面板（含取消/保存）点击失效 | 整条右键链路只用非阻塞 `QMenu.popup()` + `QTimer.singleShot(0)` 延后；预设变量显示置灰菜单项「不可编辑」，不再弹模态框（§7.3） |
| 关窗后触发 input 模板连带打开主窗口 | 输入框前 `activateIgnoringOtherApps_(True)` 激活本应用 → 触发 `on_app_state(ApplicationActive)` 把隐藏的主窗口 show 出来 | 弹框期间置 `_suppress_window_show` 标志，`on_app_state` 跳过 re-show；取消路径也 `_activate_target` 把焦点还给目标应用（§7.3） |
| 自定义胶囊悬停说明与变量库不一致 | 胶囊区构造时未注入 tooltips → 自定义变量回退默认「触发时弹窗询问值」；变量库在 `rebuild()` 现算 `custom_tooltip` | 构造时 `VariableTagBar(tooltips=_custom_tooltip_map())` 注入值来源说明（§7.3） |
| 脚本 `import csv` 崩在 import 上 | `cw:` 脚本 cwd = 脚本目录 → `sys.path[0]` 也是它，`csv.py` 导入的是**它自己** | 脚本名不与标准库同名（内置 `csv_table.py`）+ `test_shipped_scripts_avoid_stdlib_name_shadowing` 用 `find_spec` 拦住（§7.4） |
| 发货目录里冒出 `__pycache__/` | cwd = 发货目录，Python 写字节码；打包版那是只读目录 | `script_env()` 设 `PYTHONDONTWRITEBYTECODE=1`（§7.4） |
| `-2741 syntax error` 编译不过（未安装的 App） | `name of current track` 要查该 App 的术语字典——**编译期**失败，`try` 抓不住 | 先用只用基础术语的 `application "X" is running` 探测，只对运行中的 App 编译（§7.4） |
| `cw:extract url` 静默没结果 | 参数写在命令串里 → 解析不出脚本名，参数还会被丢弃 | 显式拦截并报「参数请写在模板里 `{{变量名:参数}}`」（§7.3/§7.4） |
| 打包版写 `{{脚本名}}` 的模板全部 UnknownVariableError | spec `datas` 漏了 `resources/scripts` → `load_custom_vars()` 里没有这些脚本变量 | spec 加 `("../resources/scripts", "resources/scripts")`（§7.4） |
| 变换模板「选中文本 → 输 shortcut → Tab」提取不出任何东西（**设计错误，已撤回**） | 触发靠打字，第一个字母就把要变换的选中文本覆盖掉了——`{{selection}}` 永远读空，退回剪贴板 | v9 撤回整批模板（§7.4）：打字展开与内容变换是两类东西，不该共用触发通道；变换类改做「对剪贴板条目执行，结果回剪贴板」 |
| 列表滑动「直上直下」、一格一格跳 | `QListView`/`QListWidget` 默认 `ScrollPerItem`（整行模式），触控板递来的 `pixelDelta` 被量化成整行，macOS 的连续滚动被砸碎 | 主列表一律 `setVerticalScrollMode(ScrollPerPixel)`（触控板原生连续 + 惯性即自然顺滑，不需自己补动画）（§4.0） |
| 鼠标滚轮一格瞬移一大段、无过渡 | Qt 滚轮路径不做任何缓动（`wheelScrollLines(3) × singleStep` 一次到位；像素模式主列表 = 192px/格） | `ui.animations.SmoothWheelScroller`：纵向滚轮事件动 `QScrollBar.value`，OutCubic 140–320ms；Shift+纵向/横向/无可滚范围/已在边界/减少动效 全部放行（§4.0） |
| **高刷屏**（ProMotion 14/16 吋 MBP、Pro Display XDR）上「还是不够丝滑」 | 所有自绘动画的步进间隔取自 `QScreen.refreshRate()`，而 Qt 在 macOS 上报的是**当前显示模式的标称速率**——ProMotion 常年报 **60**，面板实际能跑 120。于是我们的缓动/装饰按 60Hz 步进，系统合成的内容是 120Hz，两者错拍 | `refresh_rate()` 优先向 **`NSScreen.maximumFramesPerSecond`** 要（懒导入 AppKit，非 macOS 自动退化到 Qt）。**每次动画起步刷一次**（`apply_frame_rate`，在 `play()`/`_set_target`/`_scroll_wheel` 这些**动画起点**，不在绘制路径），屏幕换了/ProMotion 切档都能跟上（靠 5 秒 TTL 缓存）。取的是上限 120 而非此刻那一档——定时器只在动画中跑，用户一开始滚系统本来就会升到 120。诊断：`tools/diag_scroll.py` |
| 同一帧里最贵的一档装饰是**卡片抬升** | `_draw_lift` 每行画 4 层同心环，实测 dpr=2 下**单帧 +3.0ms**（其余四档合计才 ~0.8ms；基准 0.6ms）。开销基本与「环面积×层数」成正比，不是 `subtracted()` 的锅（换成整块铺同价，且整块会染到行内部——普通行底色是透明的） | **观感取舍，未改**。要降就减层数：4→3 层 **-24%**（201k 像素有微差，最大 18/255）；4→2 层 **-50%**（最大 30/255）；4 层**关抗锯齿** **-35%** 且只有 8015 像素不同（就是那圈边缘），但圆角会有点硬。`tools/diag_scroll.py` 第 3 块可以直接量 |
| 滚轮缓动「一顿一顿、掉帧」，同样距离明显不如触控板顺 | **不是绘制慢**（delegate 单帧 ~2.3ms）：`QPropertyAnimation` 走 Qt 的 `QUnifiedTimer`——**粗粒度、不锁 vsync** 的 ~16ms 时钟，一段 140ms 的滚动实测有 48ms 空档、σ≈12ms 抖动 | 换 `Qt.PreciseTimer` + `QElapsedTimer` 单调时钟自算进度（仍 OutCubic，仍可打断）：同样距离同样时长 **7 帧 / max 间隔 17.4ms / σ=0.8ms，零掉帧**。`frame_interval_ms()` = 一个屏幕刷新周期，**向下取整**（§4.0） |
| 帧率统计很漂亮但**手感依然不丝滑** | 60Hz 的真实周期是 16.67ms，四舍五入成 **17ms** 就比屏幕慢 0.33ms，两者周期性错拍——屏幕该刷新时这帧还没画完，**同一帧被显示两次**。实测：中位 17.11ms / σ 0.62ms / **零掉帧**，却是 **58.5fps**。卡的是「重复帧」，掉帧统计看不见它 | `frame_interval_ms()` 改成**向下取整**（60Hz → 16ms，跑 62.5fps）：**宁可多画一帧没被显示，不能有刷新没帧可显示**。`tools/diag_scroll.py` 第 1、2 块会直接标出「间隔 vs 理想周期」和「实测 fps vs 屏幕 Hz」 |
| 触控板「轻微一划就滑过好几屏」 | Qt 把一次输入的位移**再乘 `wheelScrollLines`（默认 3）行**；且实测 `QListView`/`QScrollArea`/`QPlainTextEdit`/`QTextEdit` **一律只看 `angleDelta`、`pixelDelta` 被完全忽略**——所以能改的只有这一条换算，不能靠像素模式 | 设置页「滚动速度」→ `app.scroll_speed`（默认 0.5 ≈ 原生一半）；缩放在 `SmoothWheelScroller` 里对**距离**乘系数，触控板仍不补动画（系统惯性曲线照旧）。倍率 1.0 = 原生，触控板原样放行（§4.0） |
| 滑动「帧率很低、肉眼可见不丝滑」 | **不是帧率问题**（实测 delegate 单帧只要 ~2.3ms、零次超 16.7ms 预算）：滚动时几乎每行都是「初次露面」，逐条播入场 → 100% 的可见行 `alpha < 0.9`（中位 0.37）、位移中位 15px，**整个视口常驻半透明中间态** | 入场只播**首次填充**那一屏；`observe` 在非 `_active and _waterfall` 时直接返回，用户一滚动（**真实滚轮/按键输入**）瀑布立即收摊。**别再给滚动加逐条入场**（§4.0） |
| 图片多的列表滚动超 60fps 预算（中位 9.77ms / p95 16.23ms / 最大 29.64ms） | 缩略图解码**同步压在 `HistoryDelegate.paint()` 里**（冷路径 3ms/张），而 `@lru_cache` 与 QPixmap 缓存**都只活在当前进程**→每次冷启动第一次滚到图片都要重解原图 | 缩略图在 `save()` 时顺手落盘 `images/<digest>.t512.png`，`thumbnail()` 优先读小文件（0.149ms，**快 20×**），老条目懒回填 + `prefetch()` 后台成批预热。同场景降到中位 1.28ms、零帧超预算（§3.5） |
| 滚动条停在列表中间时切换视图，**先白屏半秒再出数据**（看着像「加载慢」） | 整表重建只改 range 不改 value，**滚动位置被保留**；可见行是 30 号开外，而入场错峰延迟按**绝对行号** `min(row×50, 500)` 算 → 全屏都撞 500ms 封顶，整屏 `alpha=0`（实测切回历史页后可见行延迟 `[499,499,499,500,500,500]`） | 错峰基准改成**本轮首个绘制的可见行**（绘制顺序自上而下，首个 `observe` 就是视口顶行）：`min(max(0, row - base_row) × 50, 500)`。停在顶部时基准 = 0（与旧行为等价）；停在中间则顶行立即入场。`play()`/`stop()` 重置基准（§4.0） |
| 取消勾选「卡片抬升」画面毫无变化 | `_draw_lift` 读的是 `fx.activity()`，而 activity 只由「视差**或**抬升任一开着」驱动——只开视差时它照样 1.0，于是抬升永远在画 | delegate 改用 `fx.lift()`（该项关闭时恒 0），与 `parallax_for()` 检查 `_EFFECTS["parallax"]` 对称。顺手把阴影从三层/`LIFT_ALPHA=26` 提到四层/44：实测贡献从「最大差 35/255、16434 像素」升到「74/255、23252 像素」（§4.0） |
| 滚到列表中间后切类型标签 / 切视图，**入场动画不播了** | 「人滚了」原先拿 `scrollbar.valueChanged` 判断——整表重建时新的滚动范围会把当前值**夹小**，实测顺序是 `rangeChanged → valueChanged`（`clear()` 让 range 归零、`appendRows` 再撑开，值被夹下来），而且**都延后一帧**才发：`play()` 已把瀑布打开，它随后又把 `_waterfall` 关掉、`_active` 复位，动画当场消失。停在顶部时值不变（0 → 0），所以一直没暴露 | 判据换成**真实输入**：`ListEnterAnimator` 给 viewport + view 装 eventFilter，只认纵向 `Wheel` 与滚动键（一律放行）。⚠️ 过滤器要**早于**会吃掉滚轮的 `SmoothWheelScroller` 装（Qt「后装的先跑」）——历史页现在的顺序正好满足 |
| **静止**状态下切类型标签，入场动画也没了 | 过滤 `Wheel` 时**只看了事件类型、没看方向**：历史页「双指横滑切类型标签」（§4.0）也是 Wheel 事件，只是只有 x 分量、纵向滚动条一动都不动——却被当成「人滚了」把瀑布收摊 | 滚轮判据必须**判方向**，与 `SmoothWheelScroller` 一致：纵向分量非零且不弱于横向。`KeyPress` 也收窄到真能滚的那几个键（列表是 `StrongFocus`） |

| 滚动时下半屏**不停地放大缩小**（用户：「动画效果不错，就是滑动着看着有点卡顿」） | 景深的闸门算的是**瞬时速度 / 参考速度**，于是每段甩动的**惯性衰减**都会把它从 1.0 打到 ~0.09，下一次轻扫再涨回来——连扫几下就是整块下半屏反复呼吸。实测一段 20 帧的甩动：闸门 `1.00 → 0.09 → 1.00`，而**绘制根本不是瓶颈**（dpr=2 图片行也只要 3.8ms，预算 16.7ms；定时器 σ=0.53ms，零长帧） | 改成**方向闩锁**：只看本帧滚动条往哪边走（`dv > 0` 朝 1、`dv < 0` 朝 0、**`dv == 0` 保持**——惯性空隙里 dv 常是 0），乘 `activity()` 在停手后淡出。同场景闸门全程贴在 1.00。顺带把 `OverlayScrollBar.refresh()` 的每帧 `setAttribute`/`setCursor`/`update` 改成只在真变了时做 |
| 「离视口中心越远越…」这类效果做了但**看不出来** | 只有位移这一个通道（±6px）且**正中恒为 0**——而人眼正盯着中央那几行；连续平滑的位移又没有静止参照物。实测：正中 0px、上下 1/4 处只有 2–3px | 补上**缩放与明暗**两个通道（卡片自己的边界就是参照物）。落成第 5 项装饰「卡片景深」，见 §4.0/§16.1 |
| 比较两帧像素的用例**时好时坏**（明明改的不是它） | 逐项入场瀑布**由绘制驱动、随时间推进**：两次 `grab()` 之间那一屏还在淡入，像素本来就不同。实测 `test_lift_toggle_actually_disables_lift` 的第三次 shot 与第一次差 78 像素，全是入场残留 | 凡是「同一位置抓两帧比像素」的用例，先 `view._delegate.enter_animator.stop()` 推到静止再抓。另有两条同类坑：`QWidget.grab()` 会垫调色板底色（测 alpha 要用 `render(..., DrawChildren)`，§13.4），以及 `fx._timer.stop()` 后要手动钉住 `_activity` 才能隔绝衰减 |
| 老条目首见仍要付一次全解码 | 落盘缩略图是后来才加的，已入库的图没有小文件 | `ImageService.prefetch(paths)`：页面装载时把当前列表的图片路径丢进后台守护线程，几秒内整库转成小文件。降级路径（不预热）也只是「首次 3ms、之后 0.15ms」，仍比「每次启动都 3ms」好一个量级（§3.5） |
| 缩略图缓存刷掉后画出来的东西变了 | 落盘读回的 QImage 与解码路径的格式不一致（`Format_RGBA8888` vs PNG 原生格式） | 两条路径统一 `convertToFormat(Format_RGBA8888)`，测试用 `fast == slow`（QImage 逐像素相等）锁死（§3.5） |
| **Excel 整列复制**存进来是一条「细长白条，啥也看不到」 | 表格复制（Excel / Numbers / WPS 选中单元格）剪贴板**同时**放 TSV 文本 + HTML + 一张**渲染出来的位图**，而图片分支优先级最高 → 存了那张位图。它按**整个选区**渲染：实测选中一整列得到 **54×8192**、墨迹只占 **0.09%**、内容只占高度 **0.8%**（其余是空白 + 网格线）。而列表缩略图框高固定 68px、宽度按原图比例算 → 缩略图只有 **1px 宽** | `_is_table_strip()`：位图**细长**（高 ≥ 宽 × 8）**且**剪贴板文本有 ≥2 个非空行 → 不走图片分支，落下去存那份 TSV 文本（可搜索、能再粘回表格）。两条条件各自挡一类误伤：细长挡正常图片、多行文本挡浏览器右键「拷贝图像」（那也是「图片 + 文本」，但文本是单行 URL）。四条回归用例在 `tests/test_watcher.py`，两个方向都验过可证伪（§3.1） |
| 想给图片「裁掉空白边距」却裁不动 | `Image.getbbox()` **只把黑色 (0,0,0) 当背景**，白底图返回整张图（实测 60×2000 的白条返回 `(0,0,8,256)`）；而且 Excel 的位图带**网格线**（浅灰 212，占 10.6%），任何「找单一背景色」的做法都会算成「整张都是内容」 | 若要做，得自己定义墨迹（**明显深于背景**，如 < 背景灰度 − 100 → 网格线不算、文字算）+ 直方图取众数当背景 + 256 项 LUT（`point(lambda)` 会逐像素回调 Python：442K 像素要 **23ms**，换 LUT 后 **1ms**）。本轮**没做裁剪**（用户判断「效果无法保证」，实测确实如此），改走上面的存文本 |
| 快速切视图「卡顿／数据加载较慢」 | 每次进页面都完整做一遍「查库 + 重建 + 重播 800ms 瀑布 + 140ms 整页淡入」；连点几下就是一串 4-6ms 同步阻塞 + 反复重播 | ① `app/events.py` 修订号（挂 DB commit 事件）→ 四个页面 `showEvent` 脏了才 `reload()`；② `set_items` 内容指纹相同则 `animate=False`（模型照建、不重播）；③ `_fade_in_page` 250ms 节流（§4.0） |
| 用 `(id, pinned, favorite)` 当内容指纹，动画被误跳过 | 测试/新建条目 `id` 默认 0，两组不同内容撞成同一个键 | 指纹取**完整展示身份**（id/type/preview/content/file_path/pinned/favorite/session_name/language/sensitive/expires_at），别图省事取三元组（§4.0） |
| 全套测试跑到一半 **Segmentation fault**（`ui/animations.py` 的 `apply_frame_rate`） | `QWidget::screen()`。没 `show()` 过的控件没有 windowHandle，QWidget 会退化成 `QGuiApplication::screenAt(mapToGlobal(中心点))` 这条兜底路径，在那条路上调用**非确定性**地踩内存——macOS 崩溃报告的原生栈是 `QWidget::screen() → QGuiApplication::screenAt()`。同样的控件同样的调用，单独跑没事、连跑上百个用例才崩（**时序/堆布局相关**，加一句 `isValid()`/`objectName()` 都能"修好"，别被骗） | **别再从控件推屏幕**。`apply_frame_rate(timer)` 不再收控件参数，`refresh_rate()` 自己问 `NSScreen.mainScreen()` + `QApplication.primaryScreen()`。见 §16.6 的通用形式：**热路径上不碰控件** |
| 第一次滚动/第一次进页面**卡一下**（~96ms） | `refresh_rate()` 的首调用要付 `import AppKit` **78ms** + 首次 NSScreen 查询 **18ms**（实测）；而它挂在动画起点上，那次卡顿正好落在用户第一次交互 | 启动期提前付：`main.py` 在**显示主窗口之前**调 `ui.animations.prewarm_refresh_rate()`（窗口没出来时谁也看不见）。同时把 `apply_frame_rate` 从 `observe()`（**绘制驱动**，delegate.paint 每行每帧都调）挪到 `play()`——顺带修掉一个测试时序抖动：那 96ms 曾把各行起始时刻拉开 24ms，顶爆 `_starts[5]-_starts[0]` 的 ±20ms 容差 |
| 收藏夹页冒出**左右滑动的水平滚动条**（以前没有） | 面板收藏夹列表用完整 `f"{名字}（{条数}）"` 当 item 文本，名字一长就把内容宽度撑过视口（实测 `horizontal maximum = 91`） | ① 面板与条目两个列表都 `setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)`；② 面板文本按 `_PANEL_TEXT_W` 走 `elidedText`，完整名字进 `setToolTip`。条目列表本来列宽就 = 视口宽（558），永远不会出条——出条的一定是**面板**那条 |
| 设置页行内说明一长，整页**冒出横向滚动条** | 说明 `QLabel` 没开 `setWordWrap` → 按自然宽度撑宽容器（实测关掉 wrap → `horizontal maximum = 140`）。跟收藏夹那条是**同一类**：窄容器 + 不换行的长文本 | `_row()` / `_stacked_row()` 里统一 `setWordWrap(True)`；回归用例 `test_settings_page_layout_grouped_no_horizontal_scroll` 断言 `horizontalScrollBar().maximum() == 0`（已验证可证伪） |
| 收藏夹里打开代码条目，**关键词不高亮** | 收藏夹是**内容快照**（`collection_items` 与历史解耦），但快照只冗余了 content/preview/file_path——`language` 没带，而 `item_detail_popup` 拿 `item.language` 去建 Pygments lexer，空 language 就整段无色；`source_app`/`sensitive` 同理（敏感条目该遮蔽而没遮蔽） | `collection_items` 补 `language/source_app/sensitive/sensitive_type` 四列（**v10 迁移** `_upgrade_v10_collection_snapshot_metadata`，对老库用子查询回填历史里的值）；`add_item` 存、`_row_to_item` 读（`or` 兜底 NULL）。**快照要存"渲染/操作会用到的元数据"，不只是内容** |

---

## 10. Roadmap 映射

| 版本 | 内容 | 本文档对应 |
|---|---|---|
| V1 | 文本/图片/URL/文件历史、搜索、收藏、模板、Action | §3 全部就绪 |
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
- [x] 模板页（shortcut 触发 + 7 变量渲染 + 文件夹/收藏/统计 + Picker ⌘⇧S + Tab Trigger，v6）
- [x] Timeline 时间线页（今天/昨天/本周/更早按月分组，点击进详情）
- [x] **Code Mode**：代码检测（services/code_detector.py，18 语言启发式 + 置信度）+ v3 迁移元数据 + 列表 mono 预览 + 详情 Pygments 高亮 + 7 个代码 Actions
- [x] **Privacy Mode**：⌘⇧P 暂停监控 + 来源应用排除 + 敏感检测（warn/ignore/临时过期）+ 遮蔽显示 + ⌘Delete 手动删除
- [x] **滚动与切页性能**（2026-09-30 ~ 10-01）：`SmoothWheelScroller` 弃用
      `QPropertyAnimation`（Qt 的 `QUnifiedTimer` 不锁 vsync，一段 140ms 滚动里
      实测 48ms 空档、σ≈12ms）改 `Qt.PreciseTimer` + 单调时钟自算 OutCubic；
      缩略图落盘 `.t512.png`（源 256→512px）+ 懒回填 + `prefetch()` 后台预热；
      `app/events.py` 数据修订号 + 四页 `showEvent` 判脏 + `set_items` 内容指纹
      ——切页不再重查重播（§3.5 / §4.0）
- [x] **滚动视觉装饰**（`ui/scroll_fx.py`，设置页「滚动效果」逐项开关）：
      悬浮滚动条 / 上下边缘渐隐 / 缩略图视差 / 卡片抬升 / **卡片景深**（下半屏 + 只在往下翻时出现，§4.0）
- [x] 逐项入场的错峰基准改成**视口顶行**（回归：停在列表中间切视图会先白屏半秒，§4.0）
- [ ] 一次性准备打包：make_cert.sh 生成自签名证书
- [ ] build.sh 打通「打包 → 签名 → 验证 checklist」
- [ ] 性能验收：启动 <1s、万条搜索 <100ms
- [ ] **真机实测滚动装饰**：图片多的列表快速上下滚（触控板惯性）、杀进程重启
      再滚一遍（验落盘缩略图）、深/浅主题各看一眼
- [ ] 开放问题的完整清单见 **§16**（本节只排「接下来做什么」的顺序）

---

## 12. `services/` 模块参考

全项目最厚的一层（30 个文件 / 约 5.3k 行）。按职责分区，便于定位。

**「Qt」列的含义**：该文件是否 import PySide6 / pyobjc / Quartz / AppKit。
标记为「纯」的模块**没有任何 Qt/DB 依赖**，可以脱离 GUI 直接单测——新增识别类
逻辑时优先做成纯函数模块，测试成本差一个数量级。

### 12.1 剪贴板管线与存储

| 模块 | 职责 | 依赖 | Qt |
|---|---|---|---|
| `clipboard_watcher.py` | 轮询 NSPasteboard `changeCount`；解析文本/URL/图片/文件 → 去重 → 落库（§3.1） | `app.types` | 是 |
| `history_service.py` | 去重落库、FTS 索引同步、数量上限裁剪；`list_recent()` / `list_grouped()`（时间线分组也在这里） | `app.types`、`database.*`、`item_filters` | 否 |
| `search_service.py` | FTS5 全文索引 + CJK 子串兜底 + 正则（§3.4，目标 1 万条 <100ms） | `services` | 否 |
| `item_filters.py` | 「可见 / 可搜」判据：过期临时条目（§9.9）与敏感遮蔽（§9.17）。抽成一层是因为自动清扫是 24 小时周期，而条目可能是 5 分钟就过期 | `database.models` | 否 |

### 12.2 内容识别（纯函数，零 Qt/DB）

| 模块 | 职责 | 依赖 | Qt |
|---|---|---|---|
| `code_detector.py` | 18 语言启发式打分 + 置信度（阈值 0.80），结构化优先（§3.6） | — | 纯 |
| `sensitive_detector.py` | 5 类敏感模式识别 + `mask()`（§3.7 / 新增.md §9.11-9.16） | — | 纯 |

这两个模块是「策略由调用方执行，本模块只回答是不是」的范式：检测与处置分离，
所以能在没有数据库、没有窗口的情况下验证。

### 12.3 图片

| 模块 | 职责 | 依赖 | Qt |
|---|---|---|---|
| `image_service.py` | 落盘 `images/<sha256>.png`、`.t512.png` 缩略图两级缓存、`prefetch()` 后台预热、`is_managed()` 守卫（§3.5） | — | 是 |

### 12.4 模板 / Snippet

| 模块 | 职责 | 依赖 | Qt |
|---|---|---|---|
| `template_service.py` | 模板 CRUD / 文件夹 / 搜索 / 渲染流水线；shortcut 唯一校验（冲突抛 `ValueError`，不静默覆盖） | `database.*`、`template.{custom_vars,parser,renderer,variables}` | 是 |
| `snippet_service.py` | **兼容层**：代理到 `TemplateService`，旧 API 保持可用（v6 重构后） | `template_service` | 否 |

`services/template/` 子包（模板引擎，§7.3/§7.4 的落点）：

| 模块 | 职责 | Qt |
|---|---|---|
| `token.py` | token 模型（`Token` 含 `args`，供脚本传参） | 纯 |
| `parser.py` | 模板字符串 → token 流；`validate_template` 保存期校验 | 纯 |
| `renderer.py` | token 流 → 文本 + `cursor_pos` | 纯 |
| `registry.py` | 内置变量的**唯一事实源**（类别/作用/用法/例子） | 纯 |
| `variables.py` | 变量 Provider：date/time/datetime/uuid/clipboard/input/cursor（依赖注入，可测） | 纯 |
| `value_sources.py` | 自定义变量值源注册表：input/fixed/command/state 四种 | 是 |
| `custom_vars.py` | 自定义变量持久化（`template.extra_variables`）+ 旧格式迁移 | 是 |
| `scripts.py` | 发货脚本目录解析（`cw:<脚本名>` 值源） | 纯 |
| `matcher.py` | **英文** shortcut 键盘缓冲引擎 | 纯 |
| `ax_matcher.py` | **中文** shortcut 触发引擎（AX 文本末尾匹配） | 纯 |
| `ax_text.py` | AX 读焦点输入框文本 + 组合状态检测 | 是 |
| `ime.py` | 输入法检测（ctypes + HIToolbox TIS） | 纯 |
| `insertion.py` | 文本插入：模拟粘贴 + 剪贴板保存/恢复（§70-72） | 是 |
| `errors.py` | 模板错误类型（保存/渲染失败必须可读、不崩） | 纯 |

**注意中英分离是有意为之**：`matcher.py` 只处理英文 shortcut，`ax_matcher.py`
只处理中文 —— 两条通道的触发时机、误触风险、甚至删除键行为都不同（§7.3）。

### 12.5 会话与收藏

| 模块 | 职责 | 依赖 | Qt |
|---|---|---|---|
| `session_service.py` | 任务型内容分组（v4）；默认「普通」会话不可删 | `database.*` | 否 |
| `collection_service.py` | 收藏夹 + 条目**内容快照**（与历史解耦，所以删历史不影响收藏）。快照存的是**完整展示身份**：content/preview/file_path **加** language/source_app/sensitive/sensitive_type——少一样，收藏夹里的条目就画不对（代码不高亮、敏感不遮蔽） | `app.types`、`database.*` | 否 |

### 12.6 系统集成

| 模块 | 职责 | 依赖 | Qt |
|---|---|---|---|
| `hotkey_manager.py` | 自写 Quartz CGEventTap（§3.2）；不用 pynput/keyboard（它们会与监听线程的 runloop 打架） | — | 是 |
| `autostart.py` | LaunchAgent plist 管理（§4.2） | — | 否 |
| `app_identity.py` | 忽略应用的条目格式与匹配：name + bundle_id（只按名字匹配会随系统语言失效，§9.5） | — | 否 |
| `action_service.py` | Action 插件加载、筛选、执行并写回剪贴板 | — | 是 |

---

## 13. 测试指南

### 13.1 怎么跑

```bash
source .venv/bin/activate
.venv/bin/python -m pytest -q                      # 全量（712 用例，约 29s）
.venv/bin/python -m pytest tests/test_scroll_fx.py -q   # 单个文件
```

⚠️ **必须用 `.venv/bin/python`**（`source .venv/bin/activate` 之后再 `python` 也
行），别用系统 / anaconda 的解释器——见 §13.3 末尾。

**没有 `pytest.ini` / `conftest.py`**。每个测试文件自己负责三件事，新增测试文件
必须照抄这三行，否则在别的机器上会挂：

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest_app = QApplication.instance() or QApplication([])
```

### 13.2 offscreen 与「真实副作用」

绝大多数 UI 测试跑在 `QT_QPA_PLATFORM=offscreen`（无窗口），所以能进 CI。
但有几类测试**会真的动你的系统**，跑之前要知道：

| 测试文件 | 真实副作用 |
|---|---|
| `test_clipboard.py`、`test_watcher.py` | **会改写你的系统剪贴板**（用真实 NSPasteboard） |
| `test_ax_text.py` | 会触碰真实前台应用 → 测试内一律 `monkeypatch` 掉 `_frontmost_pid` 与 AX 调用 |
| `test_insertion.py` | 合成键盘事件 + AX 读焦点文本不稳定，只覆盖可纯逻辑验证的部分 |

### 13.3 按主题找用例

| 想验证 | 去哪 |
|---|---|
| 剪贴板解析 / 去重落库 | `test_watcher.py`、`test_history.py` |
| 搜索 FTS5 / CJK | `test_core.py`、`test_services_v1.py` |
| Actions 语义 | `test_actions.py` |
| 代码检测 / 敏感检测 | `test_code_detector.py`、`test_sensitive_detector.py` |
| 模板引擎全链路 | `test_template_engine.py`、`test_template_service.py`、`test_shipped_scripts.py` |
| 变量系统 / 值源 | `test_value_sources.py`、`test_variables_ux.py`、`test_scripts.py` |
| 会话 / 收藏 / 时间线 | `test_sessions.py`、`test_services_v1.py` |
| 主题 / 自绘控件 | `test_theme.py`、`test_fluent_combo.py`、`test_ui.py` |
| 动效 / 滚动 | `test_animations.py`、`test_smooth_scroll.py`、`test_scroll_fx.py`、`test_list_enter.py` |
| 切页 / 重复加载 | `test_switch_lag.py` |
| 缩略图落盘 | `test_image_thumb_cache.py` |
| 设置写回 | `test_settings.py` |

⚠️ **测试必须用 `.venv/bin/python`**，不是系统/anaconda 的 python：`pyobjc` 的
依赖是按框架分包装的，anaconda 那个环境里 `AppKit` 有、**`Quartz` 没有**，于是
`tests/test_insertion.py` 在收集阶段就 ImportError，整个测试会话直接中断。看到
「ERROR collecting tests/test_insertion.py: No module named 'Quartz'」就是解释器
用错了，不是代码坏了。

### 13.4 写测试时的既有约定

- **验收标准写在模块文档里，用例与之逐条对应。** `test_scroll_fx.py`、
  `test_list_enter.py`、`test_image_thumb_cache.py` 都是这个写法：文件头
  docstring 列出验收标准，下面的用例一条条对上去。
- **回归用例要能被证伪。** 本轮修「停在中途切页会白屏」时，先把修复临时改回去
  跑一遍确认用例真的会失败，再改回来——否则可能写了个恒过的用例。
- **测像素要绕开 Qt 的隐式底色。** `QWidget.grab()` 会把调色板底色垫在下面，
  `render()` 默认的 `DrawWindowBackground` 同样会先铺一层不透明背景；要读透明
  必须用 `QImage(Format_ARGB32_Premultiplied)` + `fill(transparent)` +
  `render(..., QImage.RenderFlag.DrawChildren)`（`test_scroll_fx._alpha_at`）。
- **全局状态用完要还原。** `ui/animations` 的滚动速度、`ui/scroll_fx` 的装饰
  开关都是**模块级**变量，测试改完必须 `finally` 还原，否则污染后面的用例。

---

## 14. 配置参考

**加载**：`app/config.py::load_config()` 把 `config/defaults.yaml`（入库、打包
内置、**禁止删除**）与 `config/settings.yaml`（用户覆盖、**不入库**，见
`.gitignore`）做**深度合并**，缺失字段回退默认值。

**写回**：`save_user_config(overrides)` 与既有用户配置深度合并后写
`settings.yaml`——所以设置页只写改动的子树，不会把默认值全量钉死。

⚠️ 设置页装载配置时必须 `blockSignals`：这些控件一旦发信号就会走 `_on_change`
把「刚从配置读出来的值」又写回 `settings.yaml`，等于打开一次设置页就把当前默认值
钉死成用户配置，以后改 `defaults.yaml` 再也不生效（`settings_view._block_signals`）。

| 段 | 键 | 默认 | 说明 |
|---|---|---|---|
| `app` | `theme` | `system` | `system` / `light` / `dark` |
| | `font_size` | `14` | 历史列表基准字号（12–16） |
| | `scroll_speed` | `0.5` | 滚动距离倍率（1.0 = Qt 原生）。触控板与鼠标滚轮共用 |
| | `scroll_effects` | 四项全 `true` | `scrollbar` / `edge_fade` / `parallax` / `lift`（§4.0） |
| | `launch_at_login` | `false` | 写入 LaunchAgent |
| `history` | `max_items` | `500` | 每会话上限（`-1` = 无限） |
| | `auto_delete_days` | `30` | 1/7/30/90/365/`-1`(永不) |
| | `poll_interval` | `0.2` | 剪贴板轮询间隔（秒） |
| | `save_images` | `true` | 是否把复制的图片存到本地 |
| | `show_image_filename` | `true` | 图片条目是否显示文件名 |
| | `max_file_size_mb` | `50` | 复制文档大小上限（`0` = 不限制） |
| | `dedupe_scope` | `all` | `all`(跨会话全局去重) / `session`(仅本会话) |
| `privacy` | `policy` | `warn` | `warn`(存但遮蔽) / `ignore`(不存) / `save_temporarily` |
| | `temp_minutes` | `5` | `save_temporarily` 的到期分钟数 |
| | `block_private_key` | `true` | 私钥类内容一律不保存（§9.15） |
| | `paused` | `false` | 暂停监控，**持久化**（重启后保持） |
| | `ignored_apps` | `[]` | 来源应用排除；新旧两种写法都支持，混用亦可（§9.5） |
| `session` | `active_id` | `1` | 激活会话 = 新内容的保存目标，重启恢复 |
| | `delete_policy` | `move` | `move`(内容移回普通，合并去重) / `delete` |
| `hotkey` | `enabled` / `keycode` / `flags` | `true` / `9` / `[command, shift]` | ⌘⇧V；用物理 vk 码，不依赖键盘布局 |
| | `privacy_keycode` | `35` | ⌘⇧P 隐私模式开关 |
| `template` | `picker_keycode` | `1` | ⌘⇧S 打开模板 Picker |
| | `default_trigger_mode` | `tab` | `tab` / `boundary` |
| | `date_format` 等三个 | strftime | `{{date}}`/`{{time}}`/`{{datetime}}` **无参数**时的格式；带参数逐次覆盖 |
| | `extra_variables` | `[]` | 用户自定义变量（结构化：`{name, description, source, config}`） |
| | `favorite_variables` | `null` | 常用变量；`null` = 全部预设 |
| `search` | `page_size` | `100` | 搜索结果分页 |

---

## 15. 扩展指南（怎么加一个新 X）

### 15.1 新增一个 Action

1. 在 `actions/` 下新建 `<名字>.py`，一个文件一个 Action（§3.3）。
2. 继承 Action 基类，实现接口；主程序**不写死**任何 Action。
3. 跑 `tests/test_actions.py` 的范式补一条语义断言（输入 → 输出）。

设计校验原则：**任何新功能先问「能否作为 Action / 插件增量加入？」**——能，
主程序不动；不能，才允许改核心。

### 15.2 新增一项设置

改动是**五处**，漏一处就会「设置页能改但不生效」或「改了不落盘」：

1. `config/defaults.yaml` — 加键 + 默认值 + 注释。
2. `ui/settings_view.py` — 建控件，**用 `_row(标题, 控件, 说明)` 加进所属分组**
   （`_section()` 开组、`_divider()` 分隔；需要整行铺开的复合控件用 `_stacked_row()`）。
   选项表（`_SCROLL_EFFECT_OPTIONS` 这类）放模块级。
   ⚠️ 说明文字会 `setWordWrap(True)`（`_row` 里已做）——不换行的话长说明会把
   页面撑宽、冒出横向条（实测关掉 wrap → `horizontal maximum = 140`）。
3. 同文件 `_load_from_config()` — 装载时把配置值填进控件。
4. 同文件 `_collect_overrides()` — 收集控件值进写回结构。
5. 同文件 `_block_signals()` — **把新控件加进屏蔽列表**（否则装载即写回，见 §14）。
6. `app/bootstrap.py` — 在 applier 表里加一个 `key: 回调` 分支让它即时生效。

### 15.3 新增一个滚动视觉装饰

照 `ui/scroll_fx.py` 现有的四个做：

1. 在 `_EFFECTS` 加键（默认 `True`），`config/defaults.yaml` 同步加一项。
2. `settings_view._SCROLL_EFFECT_OPTIONS` 加一行（键名必须与 `_EFFECTS` 一致）。
3. 装饰本体：
   - 静态装饰（滚动条、渐隐那种）→ 在 `ScrollFx.apply_settings()` 里
     `setVisible` 控制，`_place()` 里定位。
   - 动效（随滚动变化的）→ 加一个**读自己开关**的方法（如 `lift()`），
     **绝不能让 delegate 直接读 `activity()`** —— `activity` 只由「视差或抬升
     任一开着」驱动，只开视差时它照样是 1.0，直接读它会让另一个勾选框完全失效
     （用户实测报过这个 bug）。
4. 静止时必须逐像素归零：`test_frame_identical_after_scroll_settles` 会验。

### 15.4 新增一个值源 / 模板变量

- **自定义变量值源**：加一个 `ValueSourceProvider` 子类，在
  `build_value_sources()` 登记一行（`services/template/value_sources.py`）。
- **内置变量**：`services/template/registry.py` 是**唯一事实源**（类别/作用/
  用法/例子），改这里会同时驱动变量区 UI、自动补全、tooltip 与错误提示。
- **发货脚本**：往 `resources/scripts/` 丢一个读 stdin 的文件，模板里写
  `cw:<文件名>` 即可用，不必改代码。

---

## 16. 未解决问题清单（转接必读）

按「影响面 × 是否已定方案」排序。每条都标了它现在记在哪，避免同一件事在文档里
有两个说法。

### 16.1 滚动观感（本轮遗留，方案未定）

| 问题 | 现状 | 候选方案 |
|---|---|---|
| **缩略图视差几乎看不出来** | 幅度按「离视口中心的距离」给：上下边缘 ±6px、**视口正中恒为 0**，而人眼正盯着中央那几行。且它只作用于图片条目，纯文本列表完全无感 | **已按方案③落地**（2026-10-09）：新增第 5 项装饰**卡片景深**（缩放 + 向背景淡出 + 向下推），已按用户后续要求收敛为「**只作用于下半屏 + 只在往下翻列表时出现**」；景深开着时视差自动让位。理由：人眼对**面积/明暗**变化的敏感度远高于**平滑连续位移**（后者没有静止参照物）。③ 的两个替代方案（跟手滞后、加大幅度到 ±16px）未采纳——后者还要求图片行加高约 12px |
| **悬浮滚动条开关感知弱** | 它长得就像原生滚动条，开关差别不大（实测开关最大像素差 35/255、1847 像素，是四项里最弱的；渐隐 241/255、抬升 74/255 都明显得多） | 做得跟原生区分开（更细、更靠边、悬停才变粗） |
| **`demo_v.py` 的滑动效果未落地** | 参考实现在仓库根目录（未跟踪）。它是**自绘 `QAbstractScrollArea`**，不是 `QListView`——自己拿 `scroll_y` 浮点数接管滚动，所以能做橡皮筋回弹 | **视觉层可直接搬**（缩放/变暗/视差都只需 `option.rect`，与现有 `parallax_for` 同源）。**橡皮筋那层搬不了**：`QListView` 的滚动位置就是 `QScrollBar.value()`（钳在 range 内的整数），要越界回弹只能换成自绘滚动区；且 macOS 触控板自带惯性，自己接管会跟系统抢（§4.0 已定「触控板不介入」）。另：demo 的视差方向与现项目**相反**（向外推 vs 向中心收） |
| **真机实测未做** | 全部验收都在 offscreen 完成。触控板惯性、实际观感、深/浅主题下的阴影方向、杀进程重启后落盘缩略图是否生效——都还没在真机上过 | 见 §11 待办最后一条 |
| **多显示器 / 屏幕切换只认主屏** | `refresh_rate()` 现在问 `NSScreen.mainScreen()` + `QApplication.primaryScreen()`（**故意**不再从控件推屏幕，见 §9 —— 那条路会段错误），结果按 5 秒 TTL 缓存。所以把窗口拖到一块**刷新率不同**的副屏上时，步进间隔要等 ≤5 秒才跟上，且多屏是按**菜单栏那块**算的 | 想精确就跟 `QWindow.screenChanged` 清缓存（`refresh_rate_cache_clear()` 已备好），但要接在**窗口句柄**（`windowHandle()`）上、不要碰 `QWidget::screen()`。收益小（步进快一点只是多画几帧）、风险大，先记着 |

### 16.2 模板 / 变量（原文在 §7.4，此处只列条目）

- `{{cursor}}` **位置产出即被丢弃**：renderer 正确返回 `cursor_pos`，但
  `bootstrap._render_and_insert_impl` 两处都 `text, _, _ = …` → 插入后光标恒在末尾。
- `state` 值源只有 `frontmost_app` 一个状态。
- `command` 值源**同步跑在触发链路上**（默认 5s 超时，期间 UI 不响应；此时焦点已
  还给目标应用 → 超时表现为目标应用卡住后才出现文本）。
- **内置变量的参数静默丢弃**：`{{uuid:x}}` / `{{clipboard:x}}` / `{{selection:x}}` /
  `{{cursor:x}}` 的 params 在 `parse` 里根本没保留，也没有保存期提示
  （自定义变量那条已修）。
- **命令值源 cwd 固定为应用启动目录**（脚本通道除外：`cw:` 跑脚本时 cwd = 脚本所在目录）。
- **非标准前缀的 PATH 看不到**：`ensure_path` 只**追加**标准目录
  （`/usr/local/bin`、`/opt/homebrew/bin`、`/usr/bin`、`/bin`、`/usr/sbin`、`/sbin`），
  不前置、不改动已有优先级。用户机器上 `jq` 若在 `/opt/anaconda3/bin` 依然看不到
  ——所以发货脚本一律只用 Python 标准库、用应用自己的解释器跑。
- **高级语法全无**：默认值/回退（`{{x|默认}}`）、select 枚举、过滤器管道、
  日期偏移（`{{date:+1d}}`）、字面量转义（`\{\{`）。结构上受限于
  `_VAR_RE = \{\{(\w+)(?::([^}]*))?\}\}`，只支持「一个 `\w+` + 一段不含 `}` 的 params」。
- 内置变量没有「外部计算」值源（`SRC_EXTERNAL` 零引用）；`VariableMeta.value_source`
  无代码读取（纯文档元数据）。

### 16.3 变换类模板（已撤回，待重做）

2026-09-20 用户判定「选中文本 → 输 shortcut → Tab」的变换模板**形态不成立**，
v9 迁移已把 17 个发货模板整批撤回（`database/migrations.py` 的
`_WITHDRAWN_TEMPLATES` 只留作清理判据，且只删 name/shortcut/content 三项都与当初
一致的行——用户改过任何一个字就留下）。

**理由**：触发靠打字，第一个字母就把要变换的选中文本覆盖掉，输入永远拿不到；且
结果插回原处、原文没了，没法对照验证。抢抓方案（在 CGEventTap 回调里抢在按键送达
目标应用前读一次 AX 选中文本）技术上可行，但只是让一个不合理的交互勉强跑通，用户
明确否掉。

**待办**：重做成「**对剪贴板条目执行，结果回剪贴板**」。落点是历史列表右键菜单
（`ui/history_view.py::_build_menu`）加一个「变换 →」子菜单；模板需要新增「结果
去处」字段（`database/models.py` 的 `Snippet` 目前只有 `trigger_mode`）。
`resources/scripts/` 里那 12 个读 stdin 的脚本保留下来做引擎。

**核心区分**：打字展开（输入 = 你打的字，输出 = 替换它）与内容变换（输入在别处、
输出是派生）是两类东西，不该共用一条触发通道——前者根本没有「外部输入」这个概念。

### 16.4 打包与验收（未开始）

- `packaging/make_cert.sh` 生成自签名证书——**每台打包机器一次**，还没跑过。
- `packaging/build.sh` 的「打包 → 签名 → 验证 checklist」还没打通。
- 性能验收指标（启动 <1s、万条搜索 <100ms）尚未正式测。

### 16.5 已推迟的功能

| 功能 | 去处 |
|---|---|
| OCR | 插件化，见 §6.4 的打包预警（PaddleOCR 体积） |
| 图片预览、拖拽、多窗口 | 在 `ui/` 层扩展 |
| AI 插件（Summarize/Translate/Rewrite/Explain） | 需先有 AI Privacy Gateway（新增.md §9.25） |
| 第三方插件、开放 API | §3.3 的加载器已支持用户插件目录，即 V3 雏形 |
| 快捷键自定义 | 设置页现在只展示 ⌘⇧V（暂不可改） |

### 16.6 Qt 通用坑（与具体功能无关，写新代码时记得）

- **`QListWidget` 的回车会被消费并发射 `itemActivated`**，只连 `itemDoubleClicked`
  时双击能用、回车静默失效。popup 里做选择的列表必须两条信号都连。
- **调色板里的半透明项是 QSS 函数串**（`"rgba(0, 0, 0, 0.22)"`），`QColor` 不解析
  它；8 位十六进制又是 AARRGGBB 顺序。自绘控件取色必须自己解一次
  （`scroll_fx.parse_color`），且**解不出时退回兜底色，绝不返回无效 QColor**（那是黑块）。
- **`QPropertyAnimation` 走 Qt 的 `QUnifiedTimer`**——粗粒度、不锁 vsync 的 ~16ms
  时钟。对帧率敏感的滚动缓动自己用 `Qt.PreciseTimer` + `QElapsedTimer` 算进度。
- **`QImage.constBits()` 是 BGRA 字节序**，像素分析脚本按 RGBA 读会 R/B 反转。
- **别在热路径上现问某个控件"归属哪块屏幕"**。`QWidget::screen()` 对没 `show()`
  过的控件会退化成 `QGuiApplication::screenAt(mapToGlobal(中心点))`，这条兜底路径
  会非确定性地踩内存（实测：全套测试跑到一半段错误）。同理适用于任何"拿控件向上
  问全局状态"的调用。要屏幕就问 `QGuiApplication.primaryScreen()` /
  `NSScreen.mainScreen()`，或者把结果**缓存在控件创建时**。
- **"探测一次的 ObjC / 系统调用"要放在启动期付掉，别留给第一次交互动画**。
  `import AppKit` 是 **78ms**、首次 `NSScreen` 查询 **18ms**——挂在"第一次滚动/第一次
  进页面"上就是一次肉眼可见的卡顿（`ui.animations.prewarm_refresh_rate` 就是干这个的）。
- **`QWidget.paint()` 驱动的东西里不要放"可能很慢"的调用**。delegate 的
  `paint()` / 它调的 `observe()` 每行每帧都跑，一秒能跑上千次；那里只该有查表和
  算术。慢的东西（首次 import、ObjC 往返、磁盘、DB）一律挪到"动画起点"或提前预热。
