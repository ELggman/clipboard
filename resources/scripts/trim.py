#!/usr/bin/env python3
# cw: 去掉每行首尾空白，并删掉空行
import sys

lines = [line.strip() for line in sys.stdin.read().splitlines()]
sys.stdout.write("\n".join(line for line in lines if line))
