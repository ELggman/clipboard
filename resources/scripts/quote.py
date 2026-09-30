#!/usr/bin/env python3
# cw: 每行变成一个带引号的列表项（拼 SQL IN、代码数组用）
import sys


def _quote(item: str) -> str:
    return '"' + item.replace("\\", "\\\\").replace('"', '\\"') + '"'


items = [line.strip() for line in sys.stdin.read().splitlines()]
items = [i for i in items if i]
if items:
    sys.stdout.write(", ".join(_quote(i) for i in items))
