# Clipboard Workspace

> 一个专为 macOS 打造的现代化本地剪贴板工作台（Clipboard Workspace）。

---

# 一、项目目标

Clipboard Workspace 并不是一个简单的「剪贴板历史」工具，而是一个帮助用户管理复制内容、快速检索、重复利用、分类整理以及后续扩展 AI 能力的本地应用。

设计原则：

- 全部数据本地存储
- 不上传任何数据
- 不依赖任何云服务
- 响应速度优先
- UI 简洁
- 可持续扩展

---

# 二、开发环境

开发语言：

Python 3.12+

GUI：

PySide6（Qt6）

数据库：

SQLite

ORM：

SQLAlchemy

配置：

YAML

图片处理：

Pillow

OCR（后续）：

PaddleOCR

系统监听：

pyperclip
keyboard
Quartz（macOS）

打包：

PyInstaller

---

# 三、项目结构

clipboard-workspace/

├── app/
│
├── database/
│
├── models/
│
├── services/
│
├── ui/
│
├── resources/
│
├── config/
│
├── images/
│
├── logs/
│
└── main.py

---

# 四、核心模块

整个项目分为七个核心模块。

---

## 4.1 Clipboard History（历史记录）

负责监听系统剪贴板。

支持：

- Text
- Image
- File
- URL

监听到变化后：

系统剪贴板

↓

解析内容

↓

判断类型

↓

生成预览

↓

保存 SQLite

↓

刷新 UI

### 示例

复制：

Hello World

历史：

14:21

Text

Hello World

---

复制：

https://github.com

历史：

14:25

URL

GitHub

---

复制：

Screenshot.png

历史：

14:30

Image

Screenshot.png

---

### 功能

支持：

- 自动监听
- 去重
- 最大历史数量限制
- 自动删除旧记录
- Pin
- Favorite

---

## 4.2 Search（搜索）

实时搜索所有历史。

特点：

输入即可搜索。

支持：

普通搜索

例如：

mysql

立即显示：

mysql.conf

mysql docker

mysql install

支持：

- 模糊匹配
- Ignore Case
- Regex（高级模式）

排序：

默认：

最新优先

---

## 4.3 Quick Paste（快速粘贴）

快捷键：

⌘ + Shift + V

弹出：

最近历史。

例如：

────────────────

Hello

GitHub URL

Python Code

SQL

Image

────────────────

方向键：

上下移动

Enter：

重新复制

Esc：

关闭

---

## 4.4 Collections（收藏夹）

历史只是临时。

Collections 是永久保存。

例如：

工作

Prompt

邮箱模板

Linux

论文

可以：

拖入

或者：

右键：

Add To Collection

支持：

创建

删除

重命名

---

## 4.5 Snippet（代码片段）

Snippet 与 History 独立。

History：

自动产生。

Snippet：

用户维护。

例如：

名称：

email

内容：

example@gmail.com

以后：

快速复制。

支持：

变量：

{{date}}

{{time}}

{{uuid}}

例如：

Today：

{{date}}

复制后：

Today：

2026-08-06

---

## 4.6 Actions（快捷操作）

右键任意文本：

Action

例如：

JSON Pretty

Base64 Encode

Base64 Decode

URL Encode

URL Decode

Markdown Preview

Sort Lines

Remove Duplicate Lines

Upper Case

Lower Case

Trim Space

复制：

{"a":1}

↓

Pretty JSON

↓

{
    "a":1
}

自动重新进入剪贴板。

无需打开网页工具。

---

## 4.7 Timeline（时间线）

按照时间浏览。

今天

昨天

本周

例如：

14:20

Hello

↓

14:21

GitHub

↓

14:22

Image

↓

14:23

SQL

用户能够快速回顾自己的工作过程。

---

# 五、数据库设计

## clipboard_items

| 字段       | 类型     |
| ---------- | -------- |
| id         | INTEGER  |
| type       | TEXT     |
| content    | TEXT     |
| preview    | TEXT     |
| file_path  | TEXT     |
| hash       | TEXT     |
| source_app | TEXT     |
| favorite   | INTEGER  |
| pinned     | INTEGER  |
| created_at | DATETIME |
| updated_at | DATETIME |

---

## collections

| 字段       | 类型     |
| ---------- | -------- |
| id         | INTEGER  |
| name       | TEXT     |
| icon       | TEXT     |
| created_at | DATETIME |

---

## collection_items

| 字段          | 类型    |
| ------------- | ------- |
| collection_id | INTEGER |
| clipboard_id  | INTEGER |

---

## snippets

| 字段        | 类型     |
| ----------- | -------- |
| id          | INTEGER  |
| name        | TEXT     |
| content     | TEXT     |
| description | TEXT     |
| created_at  | DATETIME |

---

# 六、界面设计

左侧：

History

Collections

Snippet

Settings

右侧：

内容区域。

顶部：

Search Bar

底部：

状态栏。

整体风格：

macOS 原生。

浅色

深色

自动跟随系统。

---

# 七、设置

支持：

历史数量：

100

500

1000

无限

图片保存：

开启

关闭

自动删除：

7 天

30 天

90 天

永不

开机启动

快捷键

字体大小

主题

---

# 八、图片处理

图片不保存数据库。

ApplicationData/

Images/

xxxx.png

数据库：

只保存路径。

删除记录：

同时删除图片。

---

# 九、性能要求

启动：

<1 秒

监听：

实时

搜索：

10000 条历史

<100ms

数据库：

SQLite WAL

分页加载

图片：

懒加载

缩略图缓存

---

# 十、未来版本

V1

✅ 文本

✅ 图片

✅ 搜索

✅ 收藏

✅ Snippet

---

V1.5

增加：

OCR

图片预览

拖拽

多窗口

---

V2

增加：

AI 插件

例如：

右键：

Summarize

Translate

Rewrite

Explain

但 AI 不是核心。

只是 Action 的一种。

---

V3

支持：

Plugin

开放 API

支持第三方扩展。





# 另外

这是一个长期维护的项目，不要把 `Actions` 写死。

例如，项目目录可以设计成：

```
clipboard-workspace/

actions/
│
├── json_pretty.py
├── base64_encode.py
├── base64_decode.py
├── url_encode.py
├── markdown_preview.py
├── remove_duplicate.py
└── ...
```

每个 Action 都实现统一接口：

```
class ClipboardAction:
    id: str
    name: str
    icon: str

    def can_handle(self, clipboard_item) -> bool:
        ...

    def execute(self, clipboard_item):
        ...
```

这样以后无论新增：

- AI 总结
- AI 翻译
- OCR
- QR Code 识别
- SQL 格式化
- Python Black 格式化
- JSON 校验

都只是**新增一个 Action 插件**，主程序完全不用修改。

**这是整个项目最值得投入设计的地方**。它能把一个普通的剪贴板历史工具，演化成一个可持续扩展的「Clipboard Workspace」，后续几乎所有新功能都可以作为插件加入，而不是不断修改核心代码。