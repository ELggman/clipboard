# PyQt6 Apple Flat UI Component Design System

## 0. Role

你是一名资深的 PyQt6 UI/UX 工程师，同时具备 Apple macOS 原生应用设计经验。

你的任务不是重新设计整个应用，也不是修改现有页面的信息架构，而是：

> 在保留现有页面布局、组件位置、业务逻辑和功能行为的前提下，为整个 PyQt6 应用建立并实施一套统一的、现代化的、Apple 风格的扁平化 UI Component Design System。

本 Design System 应该适用于整个应用，而不仅仅是某一个页面。

------

# 1. Core Objective

## 1.1 Primary Goal

将现有 PyQt6 原生控件从默认 Qt / Windows 风格统一提升为：

- Modern
- Flat
- Minimal
- Native-like
- Elegant
- Professional
- Consistent

整体视觉方向：

> Apple macOS + Raycast + Linear + Modern Productivity Tools

但不要机械复制 Apple UI。

重点学习 Apple 的：

- Visual Hierarchy
- Spacing
- Typography
- Color Restraint
- Rounded Geometry
- Interaction Feedback
- Component Consistency
- Visual Simplicity

------

# 2. Non-Invasive Modification Rules

这是整个任务最重要的约束。

## 2.1 NEVER Change

未经明确要求，不得修改：

- 主窗口尺寸
- 主窗口位置
- 页面整体布局
- Grid / VBox / HBox 结构
- 页面区域数量
- 组件排列顺序
- 组件之间的业务关系
- 数据结构
- 数据库逻辑
- Signal / Slot 业务逻辑
- 页面导航逻辑
- 用户操作流程
- 现有功能

例如：

如果原页面已经是：

```text
Header
Content
Footer
```

不要修改为：

```text
Sidebar
Content
Detail
```

如果原页面存在：

```text
QLineEdit
QPushButton
QComboBox
QListWidget
```

应继续使用这些组件，优先通过样式系统改善它们。

------

## 2.2 Allowed Changes

允许：

- 修改 QSS
- 修改组件视觉样式
- 修改字体大小
- 修改颜色
- 修改 Padding
- 修改 Margin
- 修改 Border
- 修改 Border Radius
- 修改 Icon
- 修改控件高度
- 修改控件内部视觉间距
- 增加 Hover 状态
- 增加 Pressed 状态
- 增加 Focus 状态
- 增加 Selected 状态
- 增加 Disabled 状态
- 增加轻量动画或过渡效果
- 使用 SVG / QIcon 替换 Emoji
- 使用 QPalette 调整文本选择颜色
- 在 QSS 无法解决时使用 QProxyStyle
- 在列表类组件中使用 QStyledItemDelegate

------

# 3. Design Philosophy

## 3.1 Flat First

UI 应该是扁平化的。

避免：

- 厚重阴影
- 强烈渐变
- 金属质感
- 3D 按钮
- 凸起按钮
- 凹陷效果
- 大面积高饱和色块

优先：

- Flat
- Soft
- Subtle
- Layered
- Rounded

------

## 3.2 Visual Hierarchy

不要通过大量边框建立层级。

优先使用：

```text
Typography
    ↓
Color
    ↓
Spacing
    ↓
Background
    ↓
Border
    ↓
Shadow
```

边框和阴影应该是最后手段。

------

## 3.3 Visual Restraint

绝大多数组件不应该同时使用：

```text
Strong Color
+
Strong Border
+
Strong Shadow
```

例如一个 Primary Button：

推荐：

```text
Blue Background
+
White Text
+
Subtle Radius
```

而不是：

```text
Blue Background
+
Dark Border
+
Heavy Shadow
+
Gradient
```

------

# 4. Global Design Tokens

所有组件必须尽可能复用统一 Design Tokens。

不要在不同 QSS 中出现大量随机颜色和尺寸。

------

# 4.1 Color System

## Primary

```text
#007AFF
```

用途：

- Primary Button
- Selected Item
- Active Tab
- Focus
- Link
- Accent
- Important Action

------

## Primary Hover

```text
#006EE6
```

------

## Primary Pressed

```text
#005FCC
```

------

## Background

```text
#F5F5F7
```

------

## Surface

```text
#FFFFFF
```

------

## Secondary Surface

```text
#F2F2F7
```

------

## Elevated Surface

```text
#FFFFFF
```

结合轻微阴影使用。

------

## Text Primary

```text
#1D1D1F
```

------

## Text Secondary

```text
#6E6E73
```

------

## Text Tertiary

```text
#8E8E93
```

------

## Text Disabled

```text
#AEAEB2
```

------

## Border

```text
#D1D1D6
```

但必须谨慎使用。

------

## Separator

推荐：

```text
rgba(60, 60, 67, 0.12)
```

------

## Danger

```text
#FF3B30
```

------

## Danger Hover

```text
#E52D23
```

------

## Success

```text
#34C759
```

------

## Warning

```text
#FF9F0A
```

------

# 4.2 Typography

## Font

优先使用系统字体。

Windows / PyQt6 环境：

```text
Segoe UI
```

如果项目已经使用统一字体，不要强制替换全局字体。

不要为了 Apple 风格强制加载特殊字体。

------

## Font Sizes

| 用途           | 推荐    |
| -------------- | ------- |
| Window Title   | 14-16px |
| Page Title     | 20-24px |
| Section Title  | 16-18px |
| Navigation     | 14-15px |
| Button         | 13-14px |
| Body           | 13-15px |
| Secondary Text | 12-13px |
| Caption        | 11-12px |
| Tooltip        | 11-12px |

------

## Font Weight

默认：

```text
400
```

强调：

```text
500
```

标题：

```text
600
```

尽量不要滥用：

```text
700+
```

------

# 4.3 Radius System

建立统一圆角体系。

| Level  | Radius  |
| ------ | ------- |
| Small  | 6px     |
| Medium | 8px     |
| Large  | 10px    |
| XL     | 12px    |
| Card   | 14-16px |
| Dialog | 16px    |

组件应使用统一等级，而不是随机设置。

例如：

```text
Button → 8-10px
Input → 8-10px
ComboBox → 8-10px
Card → 12-16px
Menu → 10-12px
Dialog → 14-16px
```

------

# 4.4 Spacing System

统一：

```text
4
8
12
16
20
24
32
```

优先使用这些值。

避免：

```text
7
11
13
17
19
23
```

这类随机间距。

------

# 4.5 Component Heights

推荐：

| Component     | Height  |
| ------------- | ------- |
| Small Button  | 30-32px |
| Normal Button | 34-38px |
| Large Button  | 40-44px |
| Input         | 34-38px |
| ComboBox      | 34-38px |
| Tab           | 32-36px |
| Tool Button   | 30-34px |
| CheckBox      | 20-24px |
| Icon Button   | 28-34px |

如果现有布局受到固定窗口尺寸限制，应优先选择较紧凑尺寸。

------

# 5. QPushButton

## 5.1 General Rules

QPushButton 默认采用：

- Flat
- Rounded
- Minimal Border
- Clear State
- Subtle Feedback

默认：

```text
background: #F2F2F7
color: #1D1D1F
border: none
border-radius: 9px
```

------

# 5.2 Primary Button

适用于：

- Save
- Create
- Confirm
- Apply
- Main Action

```text
Normal:
#007AFF

Hover:
#006EE6

Pressed:
#005FCC

Disabled:
#C7C7CC
```

文字：

```text
white
```

------

# 5.3 Secondary Button

适用于：

- Cancel
- Back
- Secondary Action

```text
background:
#F2F2F7

color:
#1D1D1F
```

Hover：

```text
#E5E5EA
```

Pressed：

```text
#D1D1D6
```

------

# 5.4 Ghost Button

适用于：

- Toolbar
- Minor Action
- More
- Optional Action

默认：

```text
background:
transparent
```

Hover：

```text
rgba(0,0,0,0.05)
```

Pressed：

```text
rgba(0,0,0,0.10)
```

------

# 5.5 Destructive Button

适用于：

- Delete
- Remove
- Clear

默认不建议使用大面积红色。

优先：

```text
background:
transparent

color:
#FF3B30
```

Hover：

```text
rgba(255,59,48,0.10)
```

只有确认型危险操作才使用实心红色按钮。

------

# 5.6 Icon Button

例如：

```text
More
Settings
Search
Close
Delete
Favorite
```

推荐：

```text
width:
32px

height:
32px

border-radius:
8px

background:
transparent
```

Hover：

```text
#F2F2F7
```

禁止使用大型 Emoji 作为核心 UI Icon。

优先：

- SVG
- QIcon
- Lucide-style icon
- SF Symbols inspired icon

------

# 6. QToolButton

QToolButton 通常用于：

- Toolbar
- Icon Action
- Navigation
- Compact Action

默认：

```text
flat
transparent
rounded
```

Hover：

```text
#F2F2F7
```

Pressed：

```text
#E5E5EA
```

如果带文字：

```text
Icon + Text
```

必须确保 Icon 与 Text 具有合理间距。

推荐：

```text
Icon → 14-18px

Gap → 6-8px
```

------

# 7. QLineEdit

## Normal

```text
background:
#F2F2F7

border:
1px solid transparent

border-radius:
9px

padding:
0 12px
```

------

## Focus

Focus 是 Apple 风格的重要部分。

使用：

```text
background:
#FFFFFF

border:
1px solid rgba(0,122,255,0.35)
```

如果可以通过 QSS / Style 实现额外强调：

```text
subtle focus ring
```

不要使用粗重蓝色边框。

------

## Disabled

降低：

- Background Contrast
- Text Contrast

------

# 8. QComboBox

QComboBox 是重点优化对象。

------

## 8.1 Closed State

外观：

```text
background:
#F2F2F7

border:
none

border-radius:
9px
```

Text：

```text
#1D1D1F
```

------

## 8.2 Arrow

不要使用默认的 Windows 风格立体箭头。

使用：

- 简洁 Chevron
- SVG
- 自定义 QStyle

推荐：

```text
chevron-down
```

尺寸：

```text
12-14px
```

------

## 8.3 Popup

Popup 必须具有：

```text
background:
#FFFFFF

border-radius:
10-12px

padding:
4-6px
```

如果使用自定义 Popup：

建议添加极轻微阴影。

不要使用厚重阴影。

------

## 8.4 ComboBox Item

Item：

```text
height:
32-36px

padding:
0 10px

border-radius:
7-8px
```

Hover：

```text
#F2F2F7
```

Selected：

```text
rgba(0,122,255,0.10)
```

如果存在复选标记：

使用：

```text
checkmark
```

而不是粗重高亮。

------

# 9. QAbstractItemView

包括：

- QListWidget
- QListView
- QTreeWidget
- QTreeView
- QTableWidget
- QTableView

------

## 9.1 Selection

不要使用 Qt 默认深蓝色选中背景。

统一为：

```text
rgba(0,122,255,0.10)
```

Active Selection：

```text
rgba(0,122,255,0.14)
```

文字：

```text
#1D1D1F
```

------

## 9.2 Hover

Hover：

```text
#F2F2F7
```

要求：

Hover 与 Selected 必须有明确区别。

------

## 9.3 Item Spacing

不要让 Item 太高。

小型桌面工具推荐：

```text
32-48px
```

具体根据内容决定。

------

# 10. Text Selection

统一优化：

- QLineEdit
- QTextEdit
- QPlainTextEdit
- QAbstractItemView

------

## 10.1 Selection Background

不要使用默认 Windows 强蓝色。

推荐：

```text
rgba(0,122,255,0.22)
```

------

## 10.2 Selection Text

优先：

```text
#1D1D1F
```

如果背景不足以保证对比度，可以使用：

```text
white
```

必须优先保证可读性。

------

# 11. QTextEdit / QPlainTextEdit

默认：

```text
background:
#FFFFFF

border:
none

border-radius:
10px
```

内部 Padding：

```text
8-12px
```

Focus：

使用柔和 Focus Ring。

------

## ReadOnly

ReadOnly 状态不应该变成默认灰色 Disabled 样式。

应保持可读性：

```text
background:
#F7F7F9
```

------

# 12. QCheckBox

Checkbox 应该避免传统 Windows 方框感。

推荐：

- 圆角方形
- 现代 Checkmark
- 蓝色选中
- 轻量 Hover

Checked：

```text
background:
#007AFF
```

Unchecked：

```text
background:
#FFFFFF
border:
#C7C7CC
```

Disabled：

降低透明度。

------

# 13. QRadioButton

采用现代圆形 Radio：

```text
Outer Circle
+
Inner Circle
```

Selected：

```text
#007AFF
```

不要使用厚重边框。

------

# 14. QSpinBox / QDoubleSpinBox

优化：

- 外框
- 上下按钮
- Hover
- Focus
- Padding

推荐：

```text
background:
#F2F2F7

border:
none

border-radius:
9px
```

箭头使用统一简洁 Chevron。

------

# 15. QSlider

采用现代 Flat Slider。

## Track

使用浅灰：

```text
#D1D1D6
```

## Active Track

```text
#007AFF
```

## Handle

圆形：

```text
white
```

结合轻微阴影或边框。

禁止使用传统粗大 Qt Slider。

------

# 16. QTabWidget / QTabBar

优先采用：

```text
Flat Tab
```

而不是传统：

```text
3D Tab
```

------

## Normal

```text
transparent
color:
#6E6E73
```

------

## Selected

推荐：

```text
color:
#1D1D1F
```

或者使用：

```text
background:
#FFFFFF
```

配合轻微圆角。

------

## Hover

```text
#F2F2F7
```

不建议使用粗底边框。

------

# 17. QMenu

QMenu 是 Apple 风格中非常重要的区域。

------

## Background

```text
#FFFFFF
```

------

## Radius

```text
10-12px
```

------

## Padding

```text
4-6px
```

------

## Item Height

```text
30-34px
```

------

## Hover

```text
#F2F2F7
```

或者：

```text
rgba(0,122,255,0.08)
```

------

## Selected / Active

如果菜单项需要强调：

```text
rgba(0,122,255,0.10)
```

------

## Separator

不要使用深色线。

使用：

```text
rgba(60,60,67,0.12)
```

------

## Menu Icon

统一：

```text
16px
```

禁止不同菜单项使用大小不同、风格不同的 Emoji。

------

# 18. QMenuBar

如果应用使用 QMenuBar：

整体采用：

```text
flat
minimal
transparent
```

Menu Item：

```text
padding:
4px 8px

border-radius:
6px
```

Hover：

```text
#F2F2F7
```

------

# 19. QGroupBox

禁止传统：

```text
┌──────── Group ───────┐
│                      │
└──────────────────────┘
```

这种明显 Windows 框体。

更推荐：

```text
Section Title

Content
```

也就是视觉上弱化 GroupBox 边框。

如果必须保留边框：

```text
border:
1px solid rgba(60,60,67,0.12)

border-radius:
12px
```

------

# 20. QFrame

不要让所有 QFrame 都自动显示边框。

根据用途区分：

```text
Container
Divider
Card
Section
```

------

## Card Frame

```text
background:
#FFFFFF

border:
none

border-radius:
12-16px
```

------

## Divider Frame

```text
1px
rgba(60,60,67,0.12)
```

------

# 21. QScrollBar

这是 PyQt 应用非常容易暴露“默认 Qt 感”的组件。

目标：

> Scrollbar 应该存在，但不抢视觉注意力。

------

## Vertical ScrollBar

推荐：

```text
width:
8-10px
```

Handle：

```text
background:
rgba(60,60,67,0.25)

border-radius:
4-5px
```

Hover：

```text
rgba(60,60,67,0.40)
```

不要使用明显的滚动轨道颜色。

------

## Horizontal ScrollBar

保持同样规则。

------

# 22. QProgressBar

整体：

```text
background:
#E5E5EA

border:
none

border-radius:
6px
```

Chunk：

```text
#007AFF
```

高度：

```text
6-8px
```

避免传统厚重 ProgressBar。

------

# 23. QDialog

Dialog 应该：

- 简洁
- 圆角
- 清晰层级
- 低视觉噪声

推荐：

```text
background:
#FFFFFF

border-radius:
14-16px
```

标题：

```text
16-18px
600
```

正文：

```text
13-14px
```

Actions：

```text
Secondary
+
Primary
```

------

# 24. QMessageBox

不要保留默认 Windows MessageBox 风格。

视觉上：

```text
Title

Message

--------------------------------

Cancel          Confirm
```

Primary Action 位于右侧。

Danger 操作使用红色。

------

# 25. QToolTip

Tooltip：

```text
background:
rgba(30,30,30,0.92)

color:
white

border-radius:
7px

padding:
6px 8px
```

字体：

```text
11-12px
```

内容必须简洁。

------

# 26. QStatusBar

保持低存在感：

```text
background:
transparent

border:
none
```

Text：

```text
#8E8E93
```

字号：

```text
11-12px
```

------

# 27. Icon System

## 27.1 General Rule

全项目图标必须统一。

优先：

1. SVG
2. QIcon
3. Lucide 风格
4. SF Symbols 风格
5. 简洁线性 Icon

禁止：

- 大型 Emoji
- 风格混杂的 Icon
- 3D Icon
- 彩色 Emoji + 单色 Icon 混用

------

# 27.2 Icon Size

| 用途    | 推荐    |
| ------- | ------- |
| Tiny    | 12px    |
| Button  | 14-16px |
| Toolbar | 16-18px |
| Section | 18-20px |
| Large   | 24px    |

------

# 28. Global State System

所有 Interactive Component 尽可能统一支持：

```text
Normal
Hover
Pressed
Focused
Checked
Selected
Disabled
```

设计规则：

## Normal

最轻量。

## Hover

轻微 Background 改变。

## Pressed

进一步加深。

## Focused

使用柔和 Focus Ring。

## Selected

使用 Primary 的低透明度背景。

## Disabled

降低：

```text
Opacity
Contrast
```

------

# 29. Focus Ring

Focus 不应该：

```text
2-3px dark blue border
```

推荐：

```text
border:
1px solid rgba(0,122,255,0.35)
```

结合：

```text
subtle outer glow
```

达到类似 macOS 的 Focus Ring。

------

# 30. Shadow System

整体风格应尽量少使用阴影。

## Small

```text
0 1px 3px rgba(0,0,0,0.08)
```

## Medium

```text
0 4px 12px rgba(0,0,0,0.08)
```

## Large

```text
0 8px 24px rgba(0,0,0,0.10)
```

优先：

```text
Menu
Popup
Dialog
Floating Panel
```

普通 Button 不应该有明显阴影。

------

# 31. QSS Architecture

不要把所有 QSS 写在一个巨大字符串里。

推荐：

```text
styles/
│
├── theme.py
├── tokens.py
├── base.qss
│
├── button.qss
├── input.qss
├── combo_box.qss
├── menu.qss
├── list.qss
├── table.qss
├── tab.qss
├── checkbox.qss
├── slider.qss
├── scrollbar.qss
└── dialog.qss
```

如果项目规模较小，也至少应该保持：

```text
Theme Tokens
+
Global QSS
+
Component QSS
```

的逻辑层次。

------

# 32. Use Design Tokens

不要：

```python
button.setStyleSheet("""
    background: #007AFF;
    border-radius: 9px;
""")
```

在几十个地方重复。

应该集中定义：

```text
PRIMARY
PRIMARY_HOVER
SURFACE
BACKGROUND
TEXT_PRIMARY
TEXT_SECONDARY
RADIUS_SMALL
RADIUS_MEDIUM
RADIUS_LARGE
```

然后组件统一引用。

------

# 33. QPalette

对于以下内容，优先考虑 QPalette：

- Window Background
- Base
- Text
- Highlight
- HighlightedText
- Button
- ButtonText

尤其是：

```text
Text Selection
```

应保证整个应用风格一致。

------

# 34. QProxyStyle

以下情况允许使用 QProxyStyle：

- 原生 Arrow
- Complex Button Rendering
- ComboBox
- Slider
- Checkbox
- Scrollbar
- Focus Indicator

但必须遵循：

> 只有在 QSS 无法合理实现视觉要求时才使用 QProxyStyle。

不要为了简单圆角就重写 QStyle。

------

# 35. QStyledItemDelegate

对于：

- QListView
- QListWidget
- QTreeView
- QTableView

如果单纯 QSS 无法实现：

- 自定义 Item Height
- Hover
- Selection
- Icon Alignment
- Text Elision
- Custom Painting

可以使用 QStyledItemDelegate。

------

# 36. Avoid Overengineering

禁止：

为了一个按钮：

```text
创建复杂 QWidget
+
重写 paintEvent
+
创建多个 Event Filter
+
改变业务层
```

优先顺序：

```text
QSS
    ↓
QPalette
    ↓
QIcon / SVG
    ↓
QProxyStyle
    ↓
QStyledItemDelegate
    ↓
Custom Widget
```

只有前面的方案无法满足要求时，才进入下一层。

------

# 37. Existing Application Compatibility

Agent 修改项目时必须：

1. 先检查现有 UI 代码结构。
2. 识别当前使用的 PyQt6 Widget。
3. 找到现有 QSS / StyleSheet。
4. 找到 Theme / Palette 系统。
5. 判断是否已有公共组件。
6. 尽量修改已有组件。
7. 避免创建重复组件。

------

# 38. Do Not Duplicate Components

如果项目已经存在：

```text
ModernButton
SearchBox
StyledComboBox
RoundedCard
```

不要创建：

```text
AppleButton
AppleSearchBox
MacComboBox
```

而应该：

> 扩展和统一已有组件。

------

# 39. Component Naming

如果确实需要新建基础组件，应采用清晰的命名：

```text
BaseButton
PrimaryButton
IconButton
StyledComboBox
SearchLineEdit
RoundedFrame
StyledListView
```

不要：

```text
ButtonNew
Button2
NewAppleButton
ButtonFinal
ButtonFinal2
```

------

# 40. Responsive Considerations

如果窗口大小已经固定：

```text
DO NOT change window size
```

但应保证：

- 文本不被严重截断
- Button 不溢出
- Icon 不变形
- ComboBox 不裁剪
- Menu 不超出边界
- List Item 可以合理压缩

------

# 41. Small Window Optimization

如果应用窗口较小：

优先压缩：

```text
Padding
Margin
Component Height
Typography
Icon Size
```

不要优先删除功能。

例如：

```text
Button

Normal:
40px

Small Window:
34px
```

------

# 42. Apple Flat Style Do / Don't

## Do

- Soft Gray Background
- White Surface
- Blue Accent
- Rounded Corners
- Flat Buttons
- Subtle Hover
- Subtle Focus Ring
- Thin Separators
- System Font
- Consistent Icons
- High Information Clarity

## Don't

- Heavy Gradient
- 3D Button
- Strong Shadow
- Thick Border
- Large Emoji
- Random Colors
- Random Radius
- Oversized Controls
- Windows Classic Appearance
- Excessive Animation

------

# 43. Component State Matrix

每个主要组件至少检查：

| Component    | Normal | Hover    | Pressed  | Focus    | Disabled | Selected |
| ------------ | ------ | -------- | -------- | -------- | -------- | -------- |
| QPushButton  | ✓      | ✓        | ✓        | ✓        | ✓        | optional |
| QToolButton  | ✓      | ✓        | ✓        | ✓        | ✓        | ✓        |
| QLineEdit    | ✓      | optional | optional | ✓        | ✓        | -        |
| QComboBox    | ✓      | ✓        | ✓        | ✓        | ✓        | ✓        |
| QListView    | ✓      | ✓        | -        | optional | ✓        | ✓        |
| QCheckBox    | ✓      | ✓        | ✓        | ✓        | ✓        | ✓        |
| QRadioButton | ✓      | ✓        | ✓        | ✓        | ✓        | ✓        |
| QTabBar      | ✓      | ✓        | ✓        | optional | ✓        | ✓        |
| QSlider      | ✓      | ✓        | ✓        | ✓        | ✓        | ✓        |

------

# 44. Implementation Workflow

Agent 必须按照以下流程执行。

## Step 1 — Audit

扫描整个项目：

```text
PyQt6 Widgets
QSS
QPalette
QIcon
Theme
Style
Custom Widgets
```

------

## Step 2 — Inventory

建立组件清单：

```text
QPushButton: 23
QComboBox: 4
QLineEdit: 12
QMenu: 6
...
```

不要直接修改。

先理解现状。

------

## Step 3 — Define Tokens

先确定：

```text
Color
Radius
Spacing
Typography
Height
State
```

------

## Step 4 — Build Global Theme

建立统一 Theme / Style 系统。

------

## Step 5 — Optimize Base Components

建议顺序：

```text
QPushButton
QLineEdit
QComboBox
QToolButton
QCheckBox
QRadioButton
QTabBar
QMenu
QAbstractItemView
QScrollBar
QDialog
```

------

## Step 6 — Visual Consistency Pass

检查：

- 颜色
- 圆角
- 高度
- 字体
- Icon
- State
- Spacing

------

## Step 7 — Page-Level Verification

确保：

> 组件更新之后，没有破坏原有页面布局。

------

# 45. Agent Execution Rules

当收到：

```text
“美化 UI”
```

不要立即大规模修改页面。

必须先判断：

```text
这是 Layout 问题？

还是 Component Visual Problem？
```

如果用户没有要求修改 Layout：

> 默认将任务视为 Component Refinement。

------

# 46. Component Refinement Priority

视觉优化优先级：

```text
1. Typography
2. Color
3. Component Height
4. Radius
5. Spacing
6. Icon
7. State
8. Border
9. Shadow
10. Animation
```

不要一开始就添加阴影和渐变。

------

# 47. Before / After Thinking

Agent 应该始终先分析：

## Before

```text
为什么这个控件不好看？
```

例如：

- 边框太重
- 圆角不统一
- 字体过大
- 按钮过高
- Emoji 风格不一致
- Hover 缺失
- Selection 太深
- Dropdown 太传统

然后：

## After

```text
通过哪些最小修改达到改善？
```

优先采用最小侵入式修改。

------

# 48. Visual Validation

每修改一组组件，都需要检查：

## Geometry

- 是否裁剪
- 是否溢出
- 是否改变原布局
- 是否影响窗口尺寸

## Typography

- 是否清晰
- 是否统一
- 是否出现字体跳动

## Color

- 是否对比度足够
- 是否过于鲜艳
- 是否符合主题

## Interaction

- Hover 是否明显
- Pressed 是否明显
- Focus 是否明显
- Disabled 是否清楚

------

# 49. Important PyQt6 Constraint

Qt StyleSheet 并不等同于 Web CSS。

不要直接假设所有 CSS 属性都可以在 PyQt6 QSS 中工作。

例如：

- 不要无条件使用 `box-shadow`
- 不要假设 `transition` 工作方式与 Web 相同
- 不要假设 `transform` 可以直接使用
- 不要依赖复杂 CSS selector
- 不要使用浏览器专属属性

如果 QSS 无法实现目标：

> 使用 Qt 原生机制解决。

优先：

```text
QPalette
QStyle
QProxyStyle
QStyledItemDelegate
QIcon
QPainter
```

------

# 50. QSS Quality Rules

QSS 必须：

- 可读
- 可维护
- 可复用
- 有明确层次
- 避免大量重复
- 避免 `!important` 风格思维
- 避免无限叠加 Selector

------

# 51. Global Theme Requirement

最终整个应用应该表现为一个统一 Design System。

例如：

```text
History Page
    ↓
Snippet Page
    ↓
Settings Page
    ↓
Timeline Page
```

虽然页面 Layout 可以不同，但：

```text
Button
Input
ComboBox
Menu
Tab
List
Dialog
Scrollbar
```

必须保持相同的视觉语言。

------

# 52. Final UI Direction

最终效果应该接近：

```text
Apple macOS
      +
Raycast
      +
Linear
      +
Modern Developer Tool
```

关键词：

```text
Flat
Soft
Compact
Clean
Native
Consistent
Professional
```

而不是：

```text
Windows Classic
Material Design
Gaming UI
Web Admin Dashboard
```

------

# 53. Final Instruction to Agent

在整个任务过程中，请始终遵守：

```text
Do not redesign the product.

Do not redesign the layout.

Do not change the business logic.

Do not change the application behavior.

Build a consistent component system.

Refine the existing components.

Make the UI feel native, modern, flat, and Apple-inspired.
```

最终目标：

> 在不改变现有产品结构的情况下，让整个 PyQt6 应用的基础控件拥有统一、精致、现代、克制的 Apple 风格视觉语言。

------

# 54. Final Checklist

完成后必须检查：

## Global

-  Design Tokens 已统一
-  Color System 已统一
-  Radius System 已统一
-  Typography 已统一
-  Spacing 已统一

## Buttons

-  Primary
-  Secondary
-  Ghost
-  Destructive
-  Icon Button
-  Hover
-  Pressed
-  Disabled

## Inputs

-  QLineEdit
-  QTextEdit
-  QPlainTextEdit
-  Focus
-  Selection

## Selection

-  List Selection
-  Text Selection
-  ComboBox Selection
-  Tab Selection

## Menus

-  QMenu
-  QMenuBar
-  Popup
-  Separator
-  Hover

## Controls

-  QComboBox
-  QCheckBox
-  QRadioButton
-  QSpinBox
-  QSlider
-  QProgressBar

## Containers

-  QFrame
-  QGroupBox
-  QDialog
-  QMessageBox

## Scrolling

-  QScrollBar

## Icons

-  SVG / QIcon
-  Consistent Size
-  Consistent Stroke
-  No Large Emoji

## Compatibility

-  Layout unchanged
-  Window size unchanged
-  Business logic unchanged
-  Data logic unchanged
-  Existing functionality preserved
-  No unnecessary custom widgets
-  No unnecessary architectural rewrite

------

# 55. Final Principle

## Design Rule

> Reduce visual noise, not functionality.

## Implementation Rule

> Use the least invasive Qt mechanism that can achieve the desired visual result.

## Product Rule

> Preserve the existing product structure and improve the experience through component consistency.

## Visual Rule

> Flat, soft, compact, restrained, and native-looking.