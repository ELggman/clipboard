#!/usr/bin/env python3
# cw: 从 JSON 里按路径抽字段（参数形如 data.items.0.name 或 a.b[0].c）
import json
import re
import sys

if len(sys.argv) < 2 or not sys.argv[1].strip():
    print("需要路径参数，如 {{变量:data.items.0.name}}", file=sys.stderr)
    sys.exit(1)
path = sys.argv[1].strip()

try:
    current = json.loads(sys.stdin.read())
except json.JSONDecodeError as exc:
    print("不是合法 JSON：{}".format(exc), file=sys.stderr)
    sys.exit(1)

for key in [k.strip() for k in re.split(r"[.\][]", path) if k.strip()]:
    try:
        # 列表按下标、字典按键——数字键在列表上当前标用（JSON 的键全是字符串）
        current = (current[int(key)] if isinstance(current, list)
                   else current[key])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        print("路径 {} 在「{}」处取不到：{}".format(path, key, exc),
              file=sys.stderr)
        sys.exit(1)

if isinstance(current, bool):          # bool 是 int 的子类，先判
    print("true" if current else "false")
elif current is None:
    print("null")
elif isinstance(current, (dict, list)):
    print(json.dumps(current, indent=2, ensure_ascii=False))
else:
    print(current)
