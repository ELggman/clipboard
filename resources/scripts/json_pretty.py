#!/usr/bin/env python3
# cw: JSON 美化（2 空格缩进，中文不转义）
import json
import sys

try:
    data = json.loads(sys.stdin.read())
except json.JSONDecodeError as exc:
    print("不是合法 JSON：{}".format(exc), file=sys.stderr)
    sys.exit(1)
print(json.dumps(data, indent=2, ensure_ascii=False))
