#!/usr/bin/env python3
# cw: 天气（参数：城市名，省略则按 IP 定位）——数据来自 wttr.in
# cw-timeout: 10
import sys
import urllib.parse
import urllib.request

# 用标准库而不是 curl/wget：发货脚本不依赖 PATH 里有什么（见 scripts.py 的说明）
city = sys.argv[1].strip() if len(sys.argv) > 1 else ""
# `%c` 用天气图标而不是英文描述——wttr.in 的 lang 参数不翻译 format 里的 %C，
# 图标是唯一语言无关的写法；`&m` 是公制（不加会按 IP 所在地给华氏度）
url = ("https://wttr.in/" + urllib.parse.quote(city, safe="")
       + "?format=%l:+%c+%t&m")

request = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
try:
    with urllib.request.urlopen(request, timeout=8) as response:
        text = response.read().decode("utf-8", "replace")
except Exception as exc:                      # 断网/超时/DNS 都走这里
    print("取天气失败：{}".format(exc), file=sys.stderr)
    sys.exit(1)

# 图标两侧的空格数不固定，折叠成单空格
text = " ".join(text.split())
if not text:
    print("天气服务没有返回内容", file=sys.stderr)
    sys.exit(1)
print(text)
