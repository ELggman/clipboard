#!/usr/bin/env python3
# cw: 行排序（参数 desc 逆序、num 按数值、uniq 顺便去重，可组合）
import re
import sys

mode = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
lines = sys.stdin.read().splitlines()


def _number(line: str) -> float:
    """行内第一个数字（没有数字的排到最后，而不是当成 0）。"""
    match = re.search(r"-?\d+(?:\.\d+)?", line)
    return float(match.group(0)) if match else float("inf")


if "num" in mode:
    lines.sort(key=_number)
else:
    lines.sort()
if "desc" in mode:
    lines.reverse()
if "uniq" in mode:
    lines = list(dict.fromkeys(lines))
sys.stdout.write("\n".join(lines))
