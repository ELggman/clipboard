"""输入法检测：ctypes + HIToolbox TIS（不依赖被聚焦应用，全 App 通用）。

背景：中文输入法组合（marked text）无法从按键流检测（CGEventTap 在
HID 层，组合发生在更下游），AX marked range 又依赖被聚焦应用的 AX
支持（VS Code/Electron 等根本没有）。TIS 直接查当前输入源 ID，
与焦点应用无关——中文输入法激活时，所有字母输入都进组合。

⚠️ 坑：TIS 符号在 **HIToolbox**（ApplicationServices umbrella 不导出）；
加载 Carbon 主二进制是 stub、dlsym 找不到符号会崩（曾经的坑）——
必须加载 HIToolbox 本体。CFString* 符号在 CoreFoundation，单独加载。
"""
import ctypes
import logging

logger = logging.getLogger(__name__)

# HIToolbox 二进制路径（带/不带 Versions/A 都试）
_HITOOLBOX_PATHS = (
    "/System/Library/Frameworks/Carbon.framework/Versions/A/Frameworks/"
    "HIToolbox.framework/Versions/A/HIToolbox",
    "/System/Library/Frameworks/Carbon.framework/Frameworks/"
    "HIToolbox.framework/Versions/A/HIToolbox",
)
_COREFOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"

_UTF8 = 0x08000100  # kCFStringEncodingUTF8
_PROP_INPUT_SOURCE_ID = b"TISPropertyInputSourceID"

# 中文输入法输入源 ID 特征：苹果拼音/注音/五笔/双拼 = com.apple.inputmethod.SCIM.*，
# 外加搜狗/百度/讯飞/微软等第三方（注意不含 "abc"——英文 ABC 输入源是
# com.apple.inputmethod.ABC，误命中会让英文输入被当成中文）
_CN_MARKERS = ("scim", "pinyin", "zhuyin", "wubi", "cangjie",
               "shuangpin", "sogou", "baidu", "xunfei", "zh_")

_tis_lib = None
_cf_lib = None


def is_chinese_ime() -> bool:
    """当前激活输入法是否中文。失败（无库/异常）返回 False（不误伤英文）。"""
    try:
        tis = _load_tis()
        cf = _load_cf()
        if tis is None or cf is None:
            return False
        src = tis.TISCopyCurrentKeyboardInputSource()
        if not src:
            return False
        key = cf.CFStringCreateWithCString(None, _PROP_INPUT_SOURCE_ID, _UTF8)
        if not key:
            return False
        pid = tis.TISGetInputSourceProperty(src, key)
        if not pid:
            return False
        cstr = cf.CFStringGetCStringPtr(pid, _UTF8)
        if not cstr:
            return False
        sid = cstr.decode("utf-8", "ignore").lower()
        return any(m in sid for m in _CN_MARKERS)
    except Exception:
        return False


def _load_tis():
    global _tis_lib
    if _tis_lib is None:
        for path in _HITOOLBOX_PATHS:
            try:
                lib = ctypes.cdll.LoadLibrary(path)
                if hasattr(lib, "TISCopyCurrentKeyboardInputSource"):
                    lib.TISCopyCurrentKeyboardInputSource.restype = ctypes.c_void_p
                    lib.TISGetInputSourceProperty.restype = ctypes.c_void_p
                    lib.TISGetInputSourceProperty.argtypes = [
                        ctypes.c_void_p, ctypes.c_void_p]
                    _tis_lib = lib
                    break
            except OSError:
                continue
        if _tis_lib is None:
            logger.warning("HIToolbox 加载失败，中文输入法检测不可用")
    return _tis_lib


def _load_cf():
    global _cf_lib
    if _cf_lib is None:
        try:
            lib = ctypes.cdll.LoadLibrary(_COREFOUNDATION)
            lib.CFStringCreateWithCString.restype = ctypes.c_void_p
            lib.CFStringCreateWithCString.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            lib.CFStringGetCStringPtr.restype = ctypes.c_char_p
            lib.CFStringGetCStringPtr.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32]
            _cf_lib = lib
        except OSError:
            logger.warning("CoreFoundation 加载失败，中文输入法检测不可用")
    return _cf_lib
