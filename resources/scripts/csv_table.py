#!/usr/bin/env python3
# cw: CSV/TSV 转 Markdown 表格（参数 tab 表示制表符分隔）
import csv
import io
import sys


def _escape(cell: str) -> str:
    return cell.replace("|", "\\|").replace("\n", " ").strip()


delimiter = "\t" if (len(sys.argv) > 1 and
                     sys.argv[1].strip().lower() in ("tab", "tsv")) else ","
rows = [row for row in csv.reader(io.StringIO(sys.stdin.read()),
                                  delimiter=delimiter)]
if not rows:
    sys.exit(0)

width = max(len(row) for row in rows)
rows = [row + [""] * (width - len(row)) for row in rows]   # 补齐短行
out = ["| " + " | ".join(_escape(c) for c in rows[0]) + " |",
       "|" + "|".join([" --- "] * width) + "|"]
out += ["| " + " | ".join(_escape(c) for c in row) + " |"
        for row in rows[1:]]
sys.stdout.write("\n".join(out))
