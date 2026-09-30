#!/usr/bin/env python3
# cw: 字符串转义（转成能塞进 JSON/代码里的形式；参数 unescape 反向还原）
import json
import sys

# 转义串须在一行内——它本来就是给「粘进代码」用的；末尾换行不算内容
text = sys.stdin.read().rstrip("\n")
mode = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()

if mode == "unescape":
    try:
        sys.stdout.write(json.loads('"' + text + '"'))
    except json.JSONDecodeError as exc:
        print("不是合法的转义串：{}".format(exc), file=sys.stderr)
        sys.exit(1)
else:
    sys.stdout.write(json.dumps(text, ensure_ascii=False)[1:-1])
