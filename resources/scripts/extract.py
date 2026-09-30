#!/usr/bin/env python3
# cw: 抽取文本里的邮箱 / 网址 / 数字 / IP（参数 url / email / num / ip，默认 email）
import re
import sys

PATTERNS = {
    "email": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "url": r"https?://[^\s<>\"'）)】\]]+",
    "num": r"-?\d+(?:\.\d+)?",
    "ip": r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])",
}

mode = (sys.argv[1] if len(sys.argv) > 1 else "email").strip().lower()
pattern = PATTERNS.get(mode)
if pattern is None:
    print("参数只能是：{}".format(" / ".join(PATTERNS)), file=sys.stderr)
    sys.exit(1)

found = re.findall(pattern, sys.stdin.read())
if mode == "ip":                       # 正则只保证「四段数字」，这里再挡 999.1.1.1
    found = [ip for ip in found
             if all(int(part) <= 255 for part in ip.split("."))]
sys.stdout.write("\n".join(dict.fromkeys(found)))   # 去重、保序
