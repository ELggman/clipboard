# Snippet 模块开发功能需求文档

> 项目：Clipboard Workspace
> 模块：Snippet
> 文档版本：v1.0
> 开发语言：Python
> 数据库：SQLite
> 运行平台：macOS
> 设计原则：Local First / Privacy First / Developer Friendly

---

# 1. 模块概述

## 1.1 功能定位

Snippet 模块用于保存和快速插入用户经常重复输入的文本、代码、命令、模板和结构化内容。

Snippet 与 Clipboard History 的定位不同：

| 模块                | 核心问题         |
| ----------------- | ------------ |
| Clipboard History | 我之前复制过什么？    |
| Snippet           | 我经常需要输入什么？   |
| Code Mode         | 我复制的内容是不是代码？ |
| Privacy Mode      | 哪些内容不应该被保存？  |

Snippet 不应该被设计成简单的“关键词文本替换器”，而应该设计成一个轻量级的**本地模板引擎**。

整体关系：

```text
Clipboard Workspace
│
├── Clipboard History
│       └── 保存用户复制过的内容
│
├── Code Mode
│       └── 识别和处理代码
│
├── Privacy Mode
│       └── 控制敏感内容
│
└── Snippet
        ├── 固定文本
        ├── 动态变量
        ├── Clipboard 变量
        ├── 用户输入变量
        ├── 日期时间
        ├── UUID
        ├── Cursor
        └── Template
```

---

# 2. 设计目标

Snippet 模块需要满足以下目标。

## 2.1 快速

从触发 Snippet 到完成文本插入，应尽可能接近瞬时操作。

目标：

```text
普通 Snippet：
< 100 ms

简单变量：
< 100 ms

复杂模板：
< 200 ms
```

---

## 2.2 本地运行

Snippet 的核心功能必须完全在本地运行。

禁止依赖：

```text
Internet
Cloud
Remote API
LLM
```

以下功能必须完全本地：

* Snippet 存储
* Shortcut 匹配
* 模板解析
* 日期生成
* UUID 生成
* Clipboard 获取
* 用户输入
* 文本替换
* Cursor 定位

---

## 2.3 与 Clipboard History 深度结合

Snippet 应能够直接使用当前 Clipboard 内容。

例如：

```text
Snippet:

> {{clipboard}}

Date: {{date}}
```

当前 Clipboard：

```text
Hello World
```

最终：

```text
> Hello World

Date: 2026-08-07
```

---

## 2.4 支持开发者工作流

重点支持：

* Git
* Docker
* SSH
* Shell
* Python
* JavaScript
* TypeScript
* SQL
* JSON
* Markdown
* API 调试
* Bug Report
* Commit Message
* Code Template

---

# 3. 核心功能

Snippet 第一阶段必须支持：

```text
1. 创建 Snippet
2. 编辑 Snippet
3. 删除 Snippet
4. 启用 / 禁用 Snippet
5. Shortcut
6. 固定文本
7. {{date}}
8. {{time}}
9. {{datetime}}
10. {{uuid}}
11. {{clipboard}}
12. {{cursor}}
13. {{input:name}}
14. Snippet Folder
15. Snippet Search
16. Snippet Picker
17. Clipboard → Snippet
18. Snippet → Clipboard
```

---

# 4. Snippet 基础模型

一个 Snippet 至少包含：

```text
Name
Shortcut
Content
Folder
Enabled
Created At
Updated At
```

示例：

```text
Name:
Email Signature

Shortcut:
sig

Content:
Best regards,
Walter

Folder:
Work

Enabled:
Yes
```

---

# 5. 固定文本 Snippet

## 5.1 基本功能

用户可以创建：

```text
Shortcut:
shrug
```

内容：

```text
¯\_(ツ)_/¯
```

当用户触发：

```text
shrug
```

得到：

```text
¯\_(ツ)_/¯
```

---

## 5.2 常见使用场景

例如：

```text
addr
```

展开：

```text
上海市浦东新区......
```

---

```text
email
```

展开：

```text
example@example.com
```

---

```text
phone
```

展开：

```text
13800138000
```

---

```text
thanks
```

展开：

```text
Thank you for your help!
```

---

# 6. Snippet Shortcut

## 6.1 Shortcut 要求

Shortcut：

* 必须唯一；
* 区分大小写策略需要统一；
* 默认使用小写；
* 不允许为空；
* 不建议使用单字符 Shortcut。

推荐：

```text
shrug
addr
email
gitbranch
dockerlogs
bug
commit
```

不推荐：

```text
a
b
x
in
```

---

# 7. Shortcut 触发模式

系统支持三种触发模式。

---

## 7.1 Word Boundary

只有当 Shortcut 是一个完整单词时才触发。

例如：

```text
shrug
```

输入：

```text
shrug
```

之后输入：

```text
Space
```

触发：

```text
¯\_(ツ)_/¯
```

但：

```text
shrugging
```

不会触发。

---

# 7.2 Tab Trigger

推荐作为默认模式。

用户输入：

```text
shrug
```

然后：

```text
Tab
```

触发：

```text
¯\_(ツ)_/¯
```

优势：

* 不容易误触发；
* 用户容易理解；
* 对开发者尤其友好。

---

# 7.3 Automatic

用户输入：

```text
shrug
```

达到 Shortcut 后立即替换。

不建议默认启用。

适合：

```text
shrug
addr
email
```

等不容易与正常单词冲突的 Shortcut。

---

# 8. Shortcut 冲突处理

如果用户创建：

```text
Shortcut:
email
```

而系统已经存在：

```text
email
```

必须提示：

```text
Shortcut already exists.

Please choose another shortcut.
```

不允许静默覆盖。

---

# 9. Snippet Folder

Snippet 支持 Folder。

默认：

```text
All
Personal
Work
Development
Templates
```

用户可以创建：

```text
Git
Docker
Python
Email
Markdown
```

---

# 10. Folder 数据模型

Folder：

```text
id
name
created_at
updated_at
```

Snippet：

```text
folder_id
```

允许：

```text
folder_id = NULL
```

表示未分类。

---

# 11. Snippet 创建

用户可以通过：

```text
Menu Bar
    ↓
Snippets
    ↓
New Snippet
```

或者：

```text
Snippet Picker
    ↓
Create Snippet
```

---

# 12. 创建界面

建议：

```text
┌───────────────────────────────────────┐
│ New Snippet                           │
├───────────────────────────────────────┤
│ Name                                  │
│ [ Email Signature                  ]  │
│                                       │
│ Shortcut                             │
│ [ sig                             ]  │
│                                       │
│ Folder                                │
│ [ Work ▼                          ]  │
│                                       │
│ Content                               │
│ ┌───────────────────────────────────┐ │
│ │ Best regards,                     │ │
│ │ Walter                            │ │
│ └───────────────────────────────────┘ │
│                                       │
│ Trigger                               │
│ ( ) Word Boundary                     │
│ (●) Tab                               │
│ ( ) Automatic                         │
│                                       │
│                 [Cancel] [Save]       │
└───────────────────────────────────────┘
```

---

# 13. Snippet 编辑

用户可以修改：

* Name
* Shortcut
* Folder
* Content
* Trigger Mode
* Enabled

编辑时必须保留：

```text
created_at
```

只更新：

```text
updated_at
```

---

# 14. Snippet 删除

支持：

```text
Delete
```

删除前确认：

```text
Delete this snippet?

Email Signature

[Cancel] [Delete]
```

删除 Folder 时：

```text
Delete Folder?
```

需要提供：

```text
Delete folder only
Move snippets to Unfiled
Delete folder and snippets
```

推荐默认：

```text
Move snippets to Unfiled
```

---

# 15. Enable / Disable

每一个 Snippet 支持：

```text
enabled = true / false
```

Disabled Snippet：

* 不参与 Shortcut 匹配；
* 不出现在默认 Snippet Picker；
* 仍保留在数据库；
* 用户可以重新启用。

---

# 16. Snippet Picker

Snippet Picker 是核心 UI。

建议全局快捷键：

```text
⌘ + Shift + S
```

打开：

```text
┌───────────────────────────────────────┐
│ Search Snippets                       │
│ > git                                 │
├───────────────────────────────────────┤
│                                       │
│ gitbranch                             │
│ Create git branch                     │
│                                       │
│ gitcommit                             │
│ Git commit template                   │
│                                       │
│ gitignore                             │
│ Common gitignore                      │
│                                       │
└───────────────────────────────────────┘
```

---

# 17. Snippet Picker 操作

支持：

```text
↑ / ↓
Enter
Esc
```

操作：

```text
↑ ↓
选择

Enter
插入

Esc
关闭
```

---

# 18. 搜索

搜索范围：

```text
Name
Shortcut
Content
Folder
```

例如搜索：

```text
docker
```

可以匹配：

```text
dockerlogs
dockerexec
docker-compose
```

---

# 19. 搜索排序

建议排序：

```text
1. Shortcut 精确匹配
2. Name 精确匹配
3. Shortcut 前缀匹配
4. Name 前缀匹配
5. Content 匹配
6. 最近使用
```

---

# 20. Recently Used

Snippet 应记录：

```text
usage_count
last_used_at
```

例如：

```text
gitbranch
Used 132 times
Last used 2 minutes ago
```

可以用于排序。

---

# 21. Favorite

Snippet 支持：

```text
Favorite
```

收藏的 Snippet 在 Picker 中优先显示。

---

# 22. Clipboard → Snippet

这是 Clipboard Workspace 的重要特色功能。

用户在 Clipboard History 中选中一项：

```text
Right Click
    ↓
Add to Snippet
```

系统自动创建：

```text
Name:
Untitled Snippet

Shortcut:
待设置

Content:
<Clipboard Content>
```

---

# 23. 从 Clipboard 自动生成名称

例如 Clipboard：

```python
def calculate_score(user):
    return user.score * 10
```

系统可以建议：

```text
Name:
Python Function

Shortcut:
pyfunc
```

但默认不应该自动保存，用户确认后创建。

---

# 24. Clipboard → Snippet 示例

Clipboard：

```bash
docker compose logs -f backend
```

选择：

```text
Add to Snippet
```

建议：

```text
Name:
Docker Logs

Shortcut:
dockerlogs

Content:
docker compose logs -f backend
```

---

# 25. Clipboard 变量

Snippet 支持：

```text
{{clipboard}}
```

该变量代表**当前系统 Clipboard 内容**。

例如：

```text
Content:

> {{clipboard}}
```

Clipboard：

```text
Hello World
```

输出：

```text
> Hello World
```

---

# 26. Clipboard 的来源

`{{clipboard}}` 默认读取：

```text
当前系统 Clipboard
```

而不是：

```text
Snippet 历史中的某一个固定 Item
```

这样可以实现动态模板。

---

# 27. Clipboard 示例：Markdown Quote

Snippet：

```text
Shortcut:
quote

Content:
> {{clipboard}}
```

Clipboard：

```text
This is an important message.
```

触发：

```text
quote
```

结果：

```markdown
> This is an important message.
```

---

# 28. Clipboard + Date

Snippet：

```text
Shortcut:
reference

Content:
## Reference

> {{clipboard}}

Captured: {{datetime}}
```

结果：

```markdown
## Reference

> Some copied content.

Captured: 2026-08-07 17:40:12
```

---

# 29. 日期变量

第一阶段支持：

```text
{{date}}
{{time}}
{{datetime}}
```

---

# 30. {{date}}

默认格式：

```text
YYYY-MM-DD
```

例如：

```text
{{date}}
```

得到：

```text
2026-08-07
```

---

# 31. {{time}}

默认格式：

```text
HH:mm
```

例如：

```text
{{time}}
```

得到：

```text
17:40
```

---

# 32. {{datetime}}

默认格式：

```text
YYYY-MM-DD HH:mm:ss
```

例如：

```text
{{datetime}}
```

得到：

```text
2026-08-07 17:40:12
```

---

# 33. 日期格式化

支持：

```text
{{date:YYYY-MM-DD}}
{{date:YYYY/MM/DD}}
{{date:MM/DD/YYYY}}
{{date:YYYY年MM月DD日}}
```

例如：

```text
今天是 {{date:YYYY年MM月DD日}}
```

输出：

```text
今天是 2026年08月07日
```

---

# 34. 时间格式化

支持：

```text
{{time:HH:mm}}
{{time:HH:mm:ss}}
{{time:hh:mm A}}
```

---

# 35. 日期偏移

第二阶段支持：

```text
{{date:+1d}}
{{date:-1d}}
{{date:+7d}}
{{date:-1w}}
{{date:+1m}}
```

例如：

```text
Deadline: {{date:+7d}}
```

得到：

```text
Deadline: 2026-08-14
```

---

# 36. UUID

支持：

```text
{{uuid}}
```

每次触发生成新的 UUID。

例如：

```text
Request-ID: {{uuid}}
```

输出：

```text
Request-ID: 550e8400-e29b-41d4-a716-446655440000
```

UUID 必须使用 Python 标准库生成。

---

# 37. Cursor

Snippet 支持：

```text
{{cursor}}
```

表示最终文本插入后光标应该停留的位置。

例如：

```text
Hello {{cursor}}
```

输出：

```text
Hello |
```

其中：

```text
|
```

代表光标。

---

# 38. Cursor 使用场景

Markdown：

```markdown
# {{cursor}}
```

Email：

```text
Hi {{input:name}},

{{cursor}}

Best regards,
Walter
```

代码：

```python
def {{input:name}}():
    {{cursor}}
```

---

# 39. Cursor 限制

第一阶段：

```text
每个 Snippet 最多允许一个 {{cursor}}
```

如果出现：

```text
{{cursor}}
...
{{cursor}}
```

必须提示：

```text
A snippet can contain only one cursor placeholder.
```

---

# 40. 用户输入变量

支持：

```text
{{input:name}}
```

触发后弹出输入框。

例如：

```text
Hello {{input:name}}
```

用户触发：

```text
Input:

name
[ Alice                 ]

[Insert]
```

结果：

```text
Hello Alice
```

---

# 41. 多个输入变量

例如：

```text
Dear {{input:name}},

Thank you for contacting us about {{input:topic}}.

Best regards,
{{input:author}}
```

系统依次询问：

```text
name
topic
author
```

最终生成完整文本。

---

# 42. 输入变量默认值

第二阶段支持：

```text
{{input:name|Alice}}
```

如果用户直接确认：

```text
Alice
```

如果输入：

```text
Bob
```

则：

```text
Bob
```

---

# 43. 输入变量重复引用

例如：

```text
Hello {{input:name}}.

Welcome, {{name}}.
```

解析后：

```text
Hello Alice.

Welcome, Alice.
```

同一个变量应该只要求用户输入一次。

推荐内部表示：

```text
variable_id
```

而不是简单字符串替换。

---

# 44. Select 变量

第二阶段支持选择变量。

语法：

```text
{{select:type|feat|fix|refactor|docs|test|chore}}
```

触发：

```text
Type

○ feat
○ fix
○ refactor
○ docs
○ test
○ chore
```

---

# 45. Git Commit 示例

Snippet：

```text
Shortcut:
commit

Content:
{{select:type|feat|fix|refactor|docs|test|chore}}: {{cursor}}
```

用户选择：

```text
feat
```

得到：

```text
feat: |
```

---

# 46. Random

第二阶段支持：

```text
{{random:8}}
```

生成 8 位随机字符串。

例如：

```text
test-user-{{random:8}}
```

输出：

```text
test-user-a83kd92x
```

---

# 47. Random Number

第二阶段支持：

```text
{{random-number:1000:9999}}
```

结果：

```text
4821
```

---

# 48. 环境变量

高级功能支持：

```text
{{env:USER}}
{{env:HOME}}
{{env:SHELL}}
```

例如：

```text
User: {{env:USER}}
```

---

# 49. 环境变量安全要求

禁止默认暴露：

```text
PASSWORD
TOKEN
SECRET
API_KEY
PRIVATE_KEY
```

等明显敏感环境变量。

如果用户显式配置，也必须经过确认。

---

# 50. 文本转换变量

第二阶段可以支持：

```text
{{uppercase:clipboard}}
{{lowercase:clipboard}}
{{trim:clipboard}}
```

例如：

```text
{{uppercase:clipboard}}
```

Clipboard：

```text
hello world
```

输出：

```text
HELLO WORLD
```

---

# 51. URL Encode

开发者场景支持：

```text
{{urlencode:clipboard}}
```

Clipboard：

```text
hello world
```

输出：

```text
hello%20world
```

---

# 52. Base64

第二阶段支持：

```text
{{base64:clipboard}}
```

Clipboard：

```text
Hello World
```

输出：

```text
SGVsbG8gV29ybGQ=
```

---

# 53. JSON Formatter

如果 Clipboard 是 JSON：

```json
{"name":"Alice","age":25}
```

可以使用：

```text
{{json:clipboard}}
```

输出：

```json
{
    "name": "Alice",
    "age": 25
}
```

如果 Clipboard 不是合法 JSON：

```text
{{json:clipboard}}
```

必须显示错误：

```text
Clipboard is not valid JSON.
```

不得静默生成错误内容。

---

# 54. Markdown 模板

示例：

```text
Shortcut:
bug

Content:

## Bug Report

### Description
{{cursor}}

### Environment
OS: macOS
Date: {{date}}

### Steps to Reproduce
1.
2.
3.

### Expected Behavior

### Actual Behavior
```

---

# 55. Meeting 模板

```text
Shortcut:
meeting

Content:

# Meeting - {{date}}

## Participants
{{cursor}}

## Discussion

## Decisions

## Action Items
```

---

# 56. Python 模板

```text
Shortcut:
pyfunc

Content:

def {{input:name}}():
    {{cursor}}
```

输入：

```text
name:
calculate_score
```

得到：

```python
def calculate_score():
    |
```

---

# 57. Python Class 模板

```text
Shortcut:
pyclass

Content:

class {{input:name}}:
    def __init__(self):
        {{cursor}}
```

---

# 58. React 模板

```text
Shortcut:
component

Content:

function {{input:name}}() {
    return (
        <div>
            {{cursor}}
        </div>
    );
}

export default {{name}};
```

---

# 59. SQL 模板

```text
Shortcut:
sqlselect

Content:

SELECT
    {{cursor}}
FROM {{input:table}}
WHERE 1 = 1;
```

---

# 60. Docker 模板

```text
Shortcut:
dockerlogs

Content:

docker compose logs -f {{input:service}}
```

---

# 61. SSH 模板

```text
Shortcut:
ssh

Content:

ssh {{input:user}}@{{input:host}}
```

---

# 62. Curl 模板

```text
Shortcut:
curl

Content:

curl -X {{select:method|GET|POST|PUT|PATCH|DELETE}} \
  "{{input:url}}" \
  -H "Content-Type: application/json" \
  -d '{{cursor}}'
```

---

# 63. 模板解析器

Snippet Engine 必须将：

```text
{{variable}}
```

解析为 Token。

例如：

```text
Hello {{input:name}}, today is {{date}}.
```

解析：

```text
TEXT:
Hello

INPUT:
name

TEXT:
, today is

DATE:
YYYY-MM-DD

TEXT:
.
```

---

# 64. Token 类型

第一阶段：

```text
TEXT
DATE
TIME
DATETIME
UUID
CLIPBOARD
CURSOR
INPUT
```

第二阶段：

```text
SELECT
RANDOM
RANDOM_NUMBER
ENV
TRANSFORM
BASE64
URLENCODE
JSON
```

---

# 65. 模板渲染流程

```text
Snippet
   ↓
Load Content
   ↓
Parse Template
   ↓
Validate Tokens
   ↓
Collect User Inputs
   ↓
Resolve Variables
   ↓
Generate UUID / Date
   ↓
Read Clipboard
   ↓
Build Final Text
   ↓
Locate Cursor
   ↓
Insert Text
```

---

# 66. 模板验证

保存 Snippet 时进行验证。

例如：

```text
Hello {{input:name}}
```

合法。

---

错误：

```text
Hello {{input}}
```

显示：

```text
Invalid input variable.
Expected:

{{input:name}}
```

---

错误：

```text
{{unknown}}
```

显示：

```text
Unknown variable: unknown
```

---

错误：

```text
{{cursor}} text {{cursor}}
```

显示：

```text
A snippet can contain only one cursor.
```

---

# 67. 未知变量处理

不允许静默删除。

例如：

```text
Hello {{abc}}
```

如果 `abc` 未定义：

```text
Template Error

Unknown variable: abc
```

Snippet 不执行。

---

# 68. 循环引用

如果未来支持变量引用：

```text
A → B
B → A
```

必须检测循环。

最大解析深度：

```text
10
```

超过以后：

```text
Template recursion limit exceeded.
```

---

# 69. Clipboard 为空

如果：

```text
{{clipboard}}
```

但当前 Clipboard 为空：

可以输出：

```text
""
```

或者提示：

```text
Clipboard is empty.
```

推荐：

```text
允许为空
```

因为很多模板可能本身就允许空 Clipboard。

---

# 70. 插入方式

Snippet 插入不应该依赖修改应用内部内容。

采用：

```text
Keyboard / Paste Simulation
```

流程：

```text
Generate Final Text
      ↓
Save Current Clipboard
      ↓
Put Final Text Into Clipboard
      ↓
Simulate Paste
      ↓
Restore Previous Clipboard
```

---

# 71. Clipboard 恢复

Snippet 插入完成后，应尽量恢复用户原来的 Clipboard。

例如：

```text
原 Clipboard:
Hello World
```

Snippet 生成：

```text
Hello Alice
```

执行：

```text
Paste
```

完成后：

```text
Clipboard
↓
恢复 Hello World
```

---

# 72. Clipboard History 联动注意事项

Snippet 插入过程中临时修改系统 Clipboard 时：

**不能被 Clipboard Monitor 当作新的历史记录。**

因此系统需要提供：

```text
ClipboardMonitor.pause_temporarily()
```

或者：

```text
internal_clipboard_change = true
```

避免：

```text
Snippet
 ↓
修改 Clipboard
 ↓
Clipboard Monitor
 ↓
错误创建 History Item
```

---

# 73. Privacy Mode 联动

Snippet 本身属于本地数据。

但是：

```text
{{clipboard}}
```

可能把敏感 Clipboard 内容插入到目标应用。

因此：

> Snippet 不负责判断 Clipboard 是否敏感，但必须遵守 Privacy Mode 的安全策略。

---

# 74. Sensitive Clipboard

如果当前 Clipboard 被 Privacy Mode 标记：

```text
sensitive = true
```

Snippet 使用：

```text
{{clipboard}}
```

可以根据设置：

```text
Allow
Warn
Block
```

推荐默认：

```text
Warn
```

例如：

```text
This snippet will use sensitive clipboard content.

Continue?
```

---

# 75. Snippet 本身的敏感内容

例如：

```text
Shortcut:
apikey

Content:
sk-xxxxxxxxxxxxxxxx
```

Snippet 数据库本身可能保存敏感信息。

因此创建 Snippet 时可以支持：

```text
Sensitive Snippet
```

标记：

```text
sensitive = true
```

---

# 76. Sensitive Snippet UI

列表中：

```text
🔐 API Key
```

Content Preview：

```text
sk-••••••••••••
```

默认不直接显示完整内容。

---

# 77. Snippet 不上传

Snippet 数据：

```text
SQLite
```

只保存在：

```text
~/Library/Application Support/ClipboardWorkspace/
```

禁止：

```text
自动同步云端
自动上传
自动发送 AI
```

---

# 78. AI 与 Snippet

未来可以增加：

```text
Generate Snippet with AI
```

但这属于高级功能。

例如用户输入：

```text
Create a Python retry decorator snippet.
```

AI 生成：

```python
from functools import wraps
...
```

但是：

> AI 生成不是 Snippet Engine 的核心依赖。

---

# 79. AI Privacy

如果未来调用远程 AI：

必须明确提示：

```text
This request will send your prompt
to an external AI service.
```

用户确认后才能发送。

---

# 80. SQLite 数据库设计

建议：

```sql
CREATE TABLE snippet_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
```

---

# 81. snippets 表

```sql
CREATE TABLE snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL,

    shortcut TEXT NOT NULL UNIQUE,

    content TEXT NOT NULL,

    folder_id INTEGER,

    enabled INTEGER NOT NULL DEFAULT 1,

    favorite INTEGER NOT NULL DEFAULT 0,

    trigger_mode TEXT NOT NULL DEFAULT 'tab',

    sensitive INTEGER NOT NULL DEFAULT 0,

    usage_count INTEGER NOT NULL DEFAULT 0,

    last_used_at INTEGER,

    created_at INTEGER NOT NULL,

    updated_at INTEGER NOT NULL,

    FOREIGN KEY (folder_id)
        REFERENCES snippet_folders(id)
        ON DELETE SET NULL
);
```

---

# 82. 数据库索引

需要：

```sql
CREATE INDEX idx_snippets_shortcut
ON snippets(shortcut);
```

以及：

```sql
CREATE INDEX idx_snippets_folder
ON snippets(folder_id);
```

以及：

```sql
CREATE INDEX idx_snippets_last_used
ON snippets(last_used_at);
```

---

# 83. Snippet Service

建议 Python 项目结构：

```text
clipboard_workspace/
│
├── app/
│
├── clipboard/
│
├── snippets/
│   ├── __init__.py
│   ├── model.py
│   ├── repository.py
│   ├── service.py
│   ├── parser.py
│   ├── renderer.py
│   ├── matcher.py
│   ├── variables.py
│   └── errors.py
│
├── privacy/
│
├── database/
│
└── ui/
```

---

# 84. Matcher

`matcher.py` 负责：

```text
Input Text
    ↓
Shortcut Matching
    ↓
Matched Snippet
```

不负责：

```text
Template Rendering
Database
UI
```

---

# 85. Parser

`parser.py` 负责：

```text
{{date}}
{{uuid}}
{{clipboard}}
{{input:name}}
```

解析成 Token。

---

# 86. Renderer

`renderer.py` 负责：

```text
Token
 ↓
Value
 ↓
Final Text
```

例如：

```text
{{date}}
```

→

```text
2026-08-07
```

---

# 87. Variable Provider

建议：

```text
variables.py
```

提供：

```text
DateProvider
TimeProvider
UUIDProvider
ClipboardProvider
InputProvider
CursorProvider
```

未来：

```text
RandomProvider
EnvironmentProvider
TransformProvider
```

---

# 88. Service 层

`service.py` 提供：

```text
create_snippet()
update_snippet()
delete_snippet()
get_snippet()
search_snippets()
render_snippet()
use_snippet()
toggle_snippet()
favorite_snippet()
```

---

# 89. Repository 层

`repository.py` 只负责：

```text
SQLite CRUD
```

禁止 Repository 层：

```text
解析模板
处理快捷键
执行 UI
```

---

# 90. 错误处理

Snippet 失败不能导致主程序崩溃。

例如：

```text
TemplateError
ClipboardError
InputError
InsertionError
DatabaseError
```

必须被 Service 层捕获并转化成用户可理解的错误。

---

# 91. 插入失败

如果最终 Paste 失败：

```text
Snippet insertion failed.

Your original clipboard has been restored.
```

必须尽可能恢复：

```text
Original Clipboard
```

---

# 92. 数据库失败

如果 SQLite 不可用：

```text
Unable to load snippets.

Clipboard History will continue to work.
```

Snippet 模块不能导致整个 Clipboard Workspace 退出。

---

# 93. 性能要求

Shortcut Matching：

```text
< 10 ms
```

Template Parsing：

```text
< 10 ms
```

简单 Rendering：

```text
< 20 ms
```

数据库查询：

```text
< 20 ms
```

---

# 94. Snippet 使用统计

记录：

```text
usage_count
last_used_at
```

例如：

```text
gitbranch
Used 231 times
```

但不要记录：

```text
Snippet 完整内容
输入变量值
Clipboard 内容
```

在日志中。

---

# 95. 日志安全

允许：

```text
Snippet used:
id=123
shortcut=gitbranch
```

禁止：

```text
Rendered content:
git checkout -b secret-feature
```

尤其禁止记录：

```text
{{clipboard}}
{{input:name}}
{{env:...}}
```

展开后的真实值。

---

# 96. 导入 / 导出

第二阶段支持：

```text
Export Snippets
Import Snippets
```

推荐格式：

```text
JSON
```

示例：

```json
{
    "version": 1,
    "snippets": [
        {
            "name": "Git Branch",
            "shortcut": "gitbranch",
            "content": "git checkout -b feature/{{date:YYYYMMDD}}",
            "folder": "Development"
        }
    ]
}
```

---

# 97. 导出安全

如果 Snippet 被标记：

```text
sensitive = true
```

导出时：

```text
Include sensitive snippets?
```

默认：

```text
No
```

---

# 98. 备份

Snippet 数据属于用户配置。

SQLite 已经保存，因此应用可以提供：

```text
Backup
```

将：

```text
snippets
snippet_folders
```

导出到：

```text
snippets.json
```

---

# 99. 自动展开与 Snippet Picker 的关系

两种方式必须同时存在。

```text
Shortcut Trigger
       │
       ├── Automatic / Tab
       │
       └── Manual Picker
```

原因：

自动展开适合：

```text
shrug
addr
email
```

Picker 更适合：

```text
bug-report
docker-compose
python-class
react-component
```

---

# 100. 推荐默认配置

第一次启动：

```text
Snippet Enabled:
Yes

Trigger Mode:
Tab

Auto Trigger:
No

Global Picker:
⌘ + Shift + S

Clipboard Variable:
Enabled

Sensitive Clipboard Warning:
Enabled
```

---

# 101. 默认 Snippet

应用首次启动时可以创建少量示例：

```text
shrug
```

```text
¯\_(ツ)_/¯
```

---

```text
date
```

```text
{{date}}
```

---

```text
uuid
```

```text
{{uuid}}
```

---

```text
quote
```

```text
> {{clipboard}}
```

---

# 102. 示例：简单 Snippet

配置：

```text
Name:
Shrug

Shortcut:
shrug

Content:
¯\_(ツ)_/¯
```

输入：

```text
shrug<Tab>
```

结果：

```text
¯\_(ツ)_/¯
```

---

# 103. 示例：日期 Snippet

配置：

```text
Name:
Today

Shortcut:
today

Content:
Today is {{date}}
```

结果：

```text
Today is 2026-08-07
```

---

# 104. 示例：UUID Snippet

```text
Name:
UUID

Shortcut:
uuid

Content:
{{uuid}}
```

每次使用：

```text
uuid
```

都会生成不同结果。

---

# 105. 示例：Clipboard Quote

```text
Name:
Markdown Quote

Shortcut:
quote

Content:
> {{clipboard}}
```

Clipboard：

```text
Clipboard Workspace is a local-first clipboard manager.
```

结果：

```markdown
> Clipboard Workspace is a local-first clipboard manager.
```

---

# 106. 示例：Bug Report

```text
Name:
Bug Report

Shortcut:
bug

Content:

## Bug Report

### Description
{{cursor}}

### Environment
OS: macOS
Date: {{date}}

### Steps to Reproduce
1.
2.
3.

### Expected Behavior

### Actual Behavior
```

---

# 107. 示例：Git Commit

```text
Name:
Git Commit

Shortcut:
commit

Content:

{{select:type|feat|fix|refactor|docs|test|chore}}: {{cursor}}
```

结果：

```text
feat: add snippet support
```

---

# 108. 示例：SSH

```text
Name:
SSH

Shortcut:
ssh

Content:

ssh {{input:user}}@{{input:host}}
```

输入：

```text
user:
root

host:
192.168.1.100
```

得到：

```bash
ssh root@192.168.1.100
```

---

# 109. 示例：Python Function

```text
Name:
Python Function

Shortcut:
pyfunc

Content:

def {{input:name}}():
    {{cursor}}
```

输入：

```text
calculate_score
```

得到：

```python
def calculate_score():
    |
```

---

# 110. 示例：API Request

```text
Name:
API Request

Shortcut:
api

Content:

curl -X {{select:method|GET|POST|PUT|PATCH|DELETE}} \
  "{{input:url}}" \
  -H "Content-Type: application/json" \
  -d '{{cursor}}'
```

---

# 111. 第一阶段开发范围

第一阶段只实现：

```text
✓ CRUD
✓ Folder
✓ Shortcut
✓ Tab Trigger
✓ Snippet Picker
✓ Search
✓ Enabled
✓ Favorite
✓ {{date}}
✓ {{time}}
✓ {{datetime}}
✓ {{uuid}}
✓ {{clipboard}}
✓ {{cursor}}
✓ {{input:name}}
```

暂时不实现：

```text
✗ AI
✗ Environment Variable
✗ Base64
✗ URL Encode
✗ JSON Transform
✗ Random
✗ Select
```

---

# 112. 第二阶段开发范围

第二阶段：

```text
✓ Select
✓ Random
✓ Random Number
✓ Date Offset
✓ Environment Variable
✓ Uppercase
✓ Lowercase
✓ Trim
✓ Base64
✓ URL Encode
✓ JSON Formatter
✓ Import
✓ Export
```

---

# 113. 第三阶段开发范围

第三阶段：

```text
✓ Snippet Suggestions
✓ Clipboard → Snippet
✓ Usage Ranking
✓ Advanced Template Editor
✓ Sensitive Snippet
✓ Sensitive Clipboard Warning
✓ Template Validation UI
```

---

# 114. 第四阶段：AI 扩展

AI 仅作为可选增强功能：

```text
Generate Snippet
Improve Snippet
Explain Snippet
Convert Template
```

核心 Snippet Engine 不得依赖 AI。

---

# 115. 单元测试要求

必须测试：

```text
Shortcut Matching
Template Parsing
Date Rendering
Time Rendering
Datetime Rendering
UUID Rendering
Clipboard Rendering
Input Rendering
Cursor Detection
Multiple Input Variables
Invalid Variables
Unknown Variables
Duplicate Cursor
Empty Clipboard
Disabled Snippet
Shortcut Conflict
```

---

# 116. Parser 测试

输入：

```text
Hello {{date}}
```

预期：

```text
TEXT("Hello ")
DATE()
```

---

输入：

```text
{{uuid}}
```

预期：

```text
UUID()
```

---

输入：

```text
Hello {{input:name}}
```

预期：

```text
TEXT("Hello ")
INPUT(name)
```

---

# 117. Renderer 测试

输入：

```text
Today: {{date}}
```

假设日期：

```text
2026-08-07
```

输出：

```text
Today: 2026-08-07
```

---

# 118. Cursor 测试

输入：

```text
Hello {{cursor}}
```

输出：

```text
Hello
```

Cursor Position：

```text
6
```

---

# 119. Clipboard 测试

Clipboard：

```text
Hello World
```

Snippet：

```text
> {{clipboard}}
```

输出：

```text
> Hello World
```

---

# 120. 输入变量测试

模板：

```text
Hello {{input:name}}
```

输入：

```text
Alice
```

输出：

```text
Hello Alice
```

---

# 121. 错误测试

模板：

```text
{{unknown}}
```

预期：

```text
TemplateError
```

不能输出：

```text
{{unknown}}
```

也不能：

```text
""
```

---

# 122. 完整用户工作流

典型工作流：

```text
用户复制内容
      ↓
Clipboard History
      ↓
发现内容经常使用
      ↓
Add to Snippet
      ↓
设置 Shortcut
      ↓
Snippet 保存到 SQLite
      ↓
下次输入 Shortcut
      ↓
Tab
      ↓
Matcher
      ↓
找到 Snippet
      ↓
Parser
      ↓
Renderer
      ↓
解析 {{clipboard}}
{{date}}
{{uuid}}
{{input}}
{{cursor}}
      ↓
生成最终文本
      ↓
模拟 Paste
      ↓
恢复原 Clipboard
```

---

# 123. 最终模块架构

```text
                    Snippet System
                          │
          ┌───────────────┼────────────────┐
          │               │                │
       Storage          Matcher         Template
          │               │                │
       SQLite          Shortcut          Parser
          │               │                │
       Repository       Trigger          Renderer
          │                                │
       Service                     Variable Providers
                                          │
                   ┌──────────────────────┼────────────────────┐
                   │          │           │          │          │
                  Date       UUID      Clipboard    Input     Cursor
```

---

# 124. 与 Clipboard History 的最终关系

```text
                  Clipboard Workspace
                           │
             ┌─────────────┴─────────────┐
             │                           │
      Clipboard History              Snippet
             │                           │
      "我复制过什么"                "我经常输入什么"
             │                           │
             │                     Template Engine
             │                           │
             └─────────────┬─────────────┘
                           │
                     {{clipboard}}
```

其中：

```text
Clipboard History
        ↓
提供历史内容

Snippet
        ↓
提供模板

Template Engine
        ↓
组合动态内容

Paste
        ↓
插入当前应用
```

---

# 125. 功能验收标准

## 基础功能

* [ ] 可以创建 Snippet
* [ ] 可以编辑 Snippet
* [ ] 可以删除 Snippet
* [ ] 可以启用 / 禁用 Snippet
* [ ] 可以设置 Shortcut
* [ ] Shortcut 唯一性校验
* [ ] 可以创建 Folder
* [ ] 可以移动 Snippet
* [ ] 可以搜索 Snippet
* [ ] 可以收藏 Snippet
* [ ] 可以统计使用次数

## Trigger

* [ ] 支持 Word Boundary
* [ ] 支持 Tab Trigger
* [ ] 支持 Automatic
* [ ] 默认使用 Tab Trigger
* [ ] 不产生明显误触发

## Template

* [ ] 支持固定文本
* [ ] 支持 `{{date}}`
* [ ] 支持 `{{time}}`
* [ ] 支持 `{{datetime}}`
* [ ] 支持 `{{uuid}}`
* [ ] 支持 `{{clipboard}}`
* [ ] 支持 `{{cursor}}`
* [ ] 支持 `{{input:name}}`

## Clipboard

* [ ] 可以读取当前 Clipboard
* [ ] Snippet 插入不会产生错误的 Clipboard History
* [ ] Snippet 插入后可以恢复原 Clipboard
* [ ] Clipboard 为空时不会导致程序崩溃

## Security

* [ ] Snippet 完全本地运行
* [ ] 不依赖远程 API
* [ ] 不记录展开后的敏感内容
* [ ] 遵循 Privacy Mode
* [ ] Sensitive Snippet 支持 Mask
* [ ] 不自动上传 Snippet

## Reliability

* [ ] 模板解析失败不会导致应用崩溃
* [ ] 数据库错误不会导致 Clipboard Monitor 崩溃
* [ ] Paste 失败后尽可能恢复原 Clipboard
* [ ] 无效变量能够明确提示
* [ ] 重复 Cursor 能够检测
* [ ] Shortcut 冲突能够检测

---

# 126. 推荐第一版最终功能边界

第一版不应该试图做成完整的 Raycast Snippet 替代品。

最重要的是做好下面这条链路：

```text
Shortcut
   ↓
Snippet
   ↓
Template
   ↓
{{date}}
{{uuid}}
{{clipboard}}
{{input}}
{{cursor}}
   ↓
Final Text
   ↓
Paste
```

其中最重要的五个变量：

```text
{{date}}
{{uuid}}
{{clipboard}}
{{input:name}}
{{cursor}}
```

这五个变量已经能够覆盖大量实际场景。

---

# 127. 第一版示例集合

建议程序默认提供：

```text
shrug
```

```text
¯\_(ツ)_/¯
```

---

```text
today
```

```text
Today: {{date}}
```

---

```text
uuid
```

```text
{{uuid}}
```

---

```text
quote
```

```text
> {{clipboard}}
```

---

```text
bug
```

```text
## Bug Report

### Description
{{cursor}}

### Environment
OS: macOS
Date: {{date}}

### Steps to Reproduce
1.
2.
3.
```

---

```text
commit
```

```text
{{input:type}}: {{cursor}}
```

---

```text
pyfunc
```

```text
def {{input:name}}():
    {{cursor}}
```

---

# 128. 开发完成后的目标体验

用户最终应该能够形成如下使用习惯：

```text
复制东西
    ↓
Clipboard History
    ↓
偶尔需要长期保存？
    ↓
Pin

经常需要重复输入？
    ↓
Add to Snippet
    ↓
设置 Shortcut
```

之后：

```text
⌨️ 输入：

pyfunc<Tab>

↓

def calculate_score():
    |
```

或者：

```text
⌨️ 输入：

quote<Tab>

↓

> 当前 Clipboard 内容
```

或者：

```text
⌨️

bug<Tab>

↓

## Bug Report

### Description
|
```

整个过程无需打开主程序，无需网络，无需调用 AI。

---

# 129. 核心设计原则总结

Snippet 模块必须遵循以下原则：

1. **Local First**

   * 所有核心功能本地执行。

2. **Fast**

   * Shortcut 到 Paste 应该接近即时完成。

3. **Clipboard Native**

   * 与 Clipboard History 深度结合。

4. **Template First**

   * Snippet 不只是静态文本。

5. **Developer Friendly**

   * 优先服务代码、命令、Markdown、Git、API 等场景。

6. **Privacy First**

   * 不记录展开后的敏感数据。
   * 不自动上传。
   * 遵循 Privacy Mode。

7. **Simple First**

   * 第一版只实现高价值变量。
   * 不一开始引入复杂模板语言。

8. **Extensible**

   * Parser、Renderer、Variable Provider 必须模块化。
   * 后续可以增加新的变量类型而不修改核心架构。

最终目标不是简单实现：

```text
shortcut → text
```

而是实现：

```text
shortcut
    ↓
Template
    ↓
┌─────────────────────────────┐
│ Date                        │
│ Time                        │
│ UUID                        │
│ Clipboard                   │
│ User Input                  │
│ Cursor                      │
└─────────────────────────────┘
    ↓
Rendered Text
    ↓
Paste
```

从而将 Snippet 打造成 Clipboard Workspace 中与 Clipboard History 平级的核心功能模块。
