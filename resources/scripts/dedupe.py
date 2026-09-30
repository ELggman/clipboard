#!/usr/bin/env python3
# cw: 去掉重复行（保留首次出现的顺序）
import sys

seen = set()
out = []
for line in sys.stdin.read().splitlines():
    if line in seen:
        continue
    seen.add(line)
    out.append(line)
sys.stdout.write("\n".join(out))
