"""模板错误类型（文档 §66-67/§90）：保存/渲染失败必须可读、不崩溃。"""


class TemplateError(Exception):
    """模板错误基类：message 直接面向用户展示。"""

    def __init__(self, message: str, position: int = -1):
        super().__init__(message)
        self.position = position  # 模板中的出错位置（用于定位，可省略）


class UnknownVariableError(TemplateError):
    """未知变量：{{abc}} 不允许静默删除（§67）。"""


class CursorLimitError(TemplateError):
    """每个模板最多一个 {{cursor}}（§39）。"""


class InputError(TemplateError):
    """{{input}} 缺少 name 参数（§66 示例）。"""


class RenderError(TemplateError):
    """渲染阶段错误（剪贴板读取失败等）。"""
