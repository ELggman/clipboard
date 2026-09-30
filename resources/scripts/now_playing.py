#!/usr/bin/env python3
# cw: 正在播放（Spotify / 音乐 App 的当前曲目）——首次使用会弹 macOS「自动化」授权
# cw-timeout: 10
import subprocess
import sys

# 绝对路径调 osascript：不依赖 PATH
OSASCRIPT = "/usr/bin/osascript"
# 探测谁在运行。"application X is running" 是 AppleScript 基本术语，
# 对没安装的 App 也能编译——这一点很关键，见下面 TRACK 的注释。
PROBE = ('return (application "Spotify" is running) as text & ","'
         ' & (application "Music" is running) as text')
# 询问曲目的脚本**只在对应 App 确实在运行时才编译**：`name of current track`
# 属于该 App 的术语表，App 没装时整段编译不过（实测 Spotify 未安装时报
# `syntax error: 预期是","`，且是编译期错误，try 包不住）。
TRACK = (
    ("Spotify",
     'tell application "Spotify" to return (name of current track)'
     ' & " — " & (artist of current track)'),
    ("Music",
     'tell application "Music" to return (name of current track)'
     ' & " — " & (artist of current track)'),
)


def _osa(script: str):
    return subprocess.run([OSASCRIPT, "-e", script],
                          capture_output=True, text=True, timeout=8)


def _fail(message: str):
    print(message, file=sys.stderr)
    sys.exit(1)


try:
    probe = _osa(PROBE)
except Exception as exc:
    _fail("读取播放信息失败：{}".format(exc))
if probe.returncode != 0:
    _fail(probe.stderr.strip() or "osascript 返回非零")

flags = [f.strip() for f in probe.stdout.strip().split(",")]
for (app, script), flag in zip(TRACK, flags):
    if flag != "true":
        continue
    try:
        result = _osa(script)
    except Exception as exc:
        _fail("读取 {} 播放信息失败：{}".format(app, exc))
    text = result.stdout.strip() if result.returncode == 0 else ""
    if text:
        print(text)
        sys.exit(0)

# 没有在放歌 → 非零退出，让「取值失败时」策略决定插什么（默认留空）
_fail("Spotify / 音乐 都没有在播放")
