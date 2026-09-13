# PyQt-Fluent-Widgets 全量迁移可行性分析

| 项目 | 内容 |
|---|---|
| 状态 | **搁置**（待后续视情况决定是否启用） |
| 创建日期 | 2026-09-13 |
| 主题 | 是否将本应用 UI **全量迁移**到 PyQt-Fluent-Widgets |
| 评估结论 | **不建议全量迁移**（详见 §4） |

> ⚠️ **框架名待确认**：本文按实测记录当前实现为 **PySide6**（见 §2 证据）。用户后续更正称
> 「当前 UI 是 PyQt6 方案，而不是 PySide6」——该更正与代码实测不符，暂记为**未决项**。
> 若确为 PyQt6，则迁移时应选 `PyQt6-Fluent-Widgets`；若为 PySide6，则选
> `PySide6-Fluent-Widgets`。**此项影响迁移包选择，启用本方案前必须先确认。**

---

## 1. 目标库分析（PyQt-Fluent-Widgets）

**身份**：`zhiyiYo/PyQt-Fluent-Widgets`（GitHub ~8.1k stars，147 commits）。
设计语言为 **Microsoft Fluent Design / WinUI 3**（Windows 11 风格）。

**框架变体**（四包共用 `qfluentwidgets` 命名空间，只能装其一）：

| pip 包名 | 框架 | import 名 |
|---|---|---|
| `PySide6-Fluent-Widgets` | **PySide6** | `qfluentwidgets` |
| `PyQt6-Fluent-Widgets` | PyQt6 | `qfluentwidgets` |
| `PyQt-Fluent-Widgets` | PyQt5 | `qfluentwidgets` |
| `PySide2-Fluent-Widgets` | PySide2 | `qfluentwidgets` |

- 全功能版：`PyQt-Fluent-Widgets[full]`（提供 `AcrylicLabel` 亚克力标签）
- 另有付费 **Pro** 版（更多组件）与 C++ 版（需购授权）
- 附带 Qt Designer 集成（Fluent Client）

**许可（决定性）**：文档 License 页原文——
> "Non-commercial usage is licensed under GPLv3"（非商业用途 = **GPLv3**）
> "For commercial purposes, please purchase on official website"（商业用途 = **付费授权**）

即：**GPLv3 仅覆盖非商业**；商业需购买授权。GPLv3 为 copyleft（传染性）。

**组件覆盖**：
- **窗口**：`FluentWindow`、`FramelessWindow`、`StackedWindow`、`SplashScreen`（WinUI 风格标题栏 / mica 背景）
- **导航**：`NavigationInterface`（**左侧边栏**；展开/紧凑/最小模式；断点 **1008px / 1007px**）
- **基础输入**：PushButton / PrimaryPushButton / CheckBox / ComboBox / RadioButton / **SwitchButton** / Slider
- **对话框**：MessageBox / Dialog / ColorDialog / FolderListDialog / FolderListSettingCard（Win10 风格）
- **状态提示**：**InfoBar** / StateToolTip / ToolTip
- **设置页**：`SettingCard` 系列（Switch / ComboBox / Range / Color / Push / Options / Hyperlink …）+ `SettingCardGroup` + 自带 `qconfig` 配置体系
- **主题**：`setTheme(LIGHT/DARK/AUTO)` + `setThemeColor()`，配 `StyleSheetBase`（**样式表机制，非 QPalette**）
- **动画/布局**：`common/animation`、`FlowLayout`、`AcrylicLabel`

---

## 2. 当前项目 UI 现状

- **GUI 框架（实测）**：**PySide6 ≥6.9**（代码 38 个文件 `import PySide6`，0 个 `PyQt6`；
  `requirements.txt` 为 `PySide6>=6.9.0`；本机安装 PySide6 6.11.1；`DEVELOPMENT.md` 技术栈表列为 `PySide6 (Qt6)`）
- **许可**：**MIT**（仓库根 `LICENSE`）
- **形态**：macOS **菜单栏常驻 App（LSUIElement）**，固定 **420×700** 面板
- **UI 规模**：`ui/` 目录 **24 个文件 / ~7,650 行**
- **主题**：自绘 **QSS**（`ui/theme.py` **645 行 / 110 条规则**），浅色 + 深色双套；
  `QPalette` 把 accent 颜色塞入 `Link` role 供委托读取；运行时切换原生 NSAppearance
- **自绘绘制（7 处）**：`HistoryDelegate` / `TemplateCardDelegate` / `NavItemDelegate` /
  QuickPaste `_RowDelegate` / `FolderSourceDelegate` / 详情 gutter / `_FlowLayout`
  —— 承载代码预览、图片缩略图、选中胶囊等核心观感
- **无边框弹层（4 个 `Qt.Popup` = macOS NSPanel）**：Quick Paste / 模板 Picker / 条目详情 / 变量库，
  配 `ui/macos_patch.py`（QNSPanel `canBecomeKeyWindow` **白名单 + 委托原实现**）
- **其他**：QPainter 自绘图标工厂（14 图标）、`HoverAnimator` 悬停动画、
  顶部导航 `QListWidget` + `QStackedWidget`（历史/收藏/模板/时间线/设置 5 页）

---

## 3. 可行性分析

### 🔴 硬性阻碍（决定性）

**3.1 许可证冲突 —— 决定性问题**
本项目 **MIT**；该库 **GPLv3（copyleft，传染）**。一旦链接分发，**整个应用须改为 GPLv3 开源**，
或**购买商业授权**。对 MIT 项目而言是法律层面阻断点，通常直接否决。

**3.2 设计语言错配 —— 决定性问题**
这是面向 **macOS** 的原生菜单栏应用（刻意模仿 macOS：accent `#2E90FF`、半透明圆角卡片、
原生 NSPanel 弹层、原生 QComboBox）。Fluent 为 **Windows/WinUI** 美学。
全量迁移 = 在 macOS 上呈现「Windows 程序」观感，**属观感倒退而非优化**。

### 🟠 结构性阻碍

**3.3 会作废刚完成的 macOS 键盘修复**
Quick Paste / Picker 等弹层依赖 `Qt.Popup` + `macos_patch.py`（QNSPanel key-window 白名单+委托）。
Fluent 有各自的窗口/弹层类（≠ `Qt.Popup`），迁移 = **从零重解 macOS 键盘路由**，回归风险极高。

**3.4 导航模型不匹配**
`NavigationInterface` 为**左侧边栏**，断点按 **1008px** 设计；本项目为 **420px 宽顶部导航条**，
在 420px 下只会落入 MINIMAL/COMPACT（纯图标/菜单按钮），不可用。

**3.5 自定义绘制与主题无法沿用**
- 7 条自绘路径 Fluent 无对应控件 → 只能保留自绘（迁移无收益）或重写（大量返工）
- `theme.py` 的 110 条 QSS 与 Fluent 的 `StyleSheetBase` + `qconfig` **是两套互斥体系**；
  Fluent `setTheme` 只驱动其自家控件，**不管自绘控件**，混用会互相打架

**3.6 `FluentWindow` 是常规窗口**
带 WinUI 标题栏 / 最小化 / 最大化 / mica 背景，**非菜单栏 accessory 面板**；
与 LSUIElement + 托盘 + 全局热键形态不契合。

### 🟢 可借鉴的部分（局部收益）

- **InfoBar / StateToolTip**：toast 提示交互模式
- **SwitchButton**：设置页开关观感
- **SettingCardGroup**：设置页组织方式（注意其自带 config 体系会与项目 config 冲突）
- **common/animation**：缓动 / 展开展合动效思路

---

## 4. 结论与工作量

**工作量**：全量迁移 ≈ **重写全部 UI（24 文件 / 7.6k 行）+ 重解 macOS 弹窗/键盘 +
弃用 `theme.py` / `macos_patch.py`**，数周级，且**净观感为负**。

### 📌 结论：不建议全量迁移

理由排序：**① 许可证（GPLv3 vs MIT）** > **② 设计语言（WinUI 对 macOS 原生）** >
③ 会作废 macOS 修复 + 自绘/主题体系冲突。

**若仍要采用**，前置条件缺一不可：
1. 购买**商业授权**（或接受 GPLv3 开源）
2. 接受 **macOS 上呈 Windows 观感**
3. 规划弹窗/委托/主题重写 + macOS 键盘重测

### 建议替代路线

1. **保留 macOS 原生设计**，做像素级打磨（间距/字号/曲线/动效）——收益最大、零风险
2. **选择性借鉴 Fluent 交互**（InfoBar 式提示、开关、展开展合动画），**不引入 GPL 依赖**
3. 若确要 Fluent 观感，**照其设计规范自研关键组件**（规避 GPL 传染）

---

## 5. 待办 / 附录

- [ ] **确认 GUI 框架**：PySide6（代码实测）还是 PyQt6（用户更正）→ 决定迁移包名
- [ ] 若启用：确认商业授权采购或接受 GPLv3
- [ ] 若启用：先做 **PoC**（单页迁移 + macOS 弹窗键盘回归验证），再评估全量
- 参考链接：
  - 文档：<https://pyqt-fluent-widgets.readthedocs.io/en/latest/index.html>
  - 仓库：<https://github.com/zhiyiYo/PyQt-Fluent-Widgets>
  - 授权价格：<https://qfluentwidgets.com/price>
