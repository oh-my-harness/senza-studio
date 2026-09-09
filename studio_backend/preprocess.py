"""Spec 预处理器——实现已搬到 senza_studio_runtime（Phase 7）。

这里只做转发，保留 studio_backend.preprocess 这个导入路径：Studio 内部和测试
都在用它，而且预处理器现在必须是 Studio 和导出项目**共用的同一份**——各留一份
拷贝的话，"导出项目行为和 Studio 里一致"这条验收就只能靠人盯着，迟早漂移。
"""
from __future__ import annotations

from senza_studio_runtime.preprocess import (  # noqa: F401
    PreprocessError,
    expand_component,
    preprocess_spec,
)

__all__ = ["PreprocessError", "expand_component", "preprocess_spec"]
