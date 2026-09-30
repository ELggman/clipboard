#!/usr/bin/env python3
# cw: 每词首字母大写（其余字母转小写；中文等无大小写的字符原样保留）
import re
import sys


def _cap(match: "re.Match") -> str:
    word = match.group(0)
    return word[:1].upper() + word[1:].lower()


sys.stdout.write(re.sub(r"\w+", _cap, sys.stdin.read()))
