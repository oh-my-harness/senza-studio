"""元 agent 工具集：spec / doc / prefab 工具回调。"""
from .spec_tools import make_spec_tools, make_spec_callbacks
from .doc_tools import make_doc_tools, make_doc_callbacks
from .prefab_tools import make_prefab_tools, make_prefab_callbacks

__all__ = [
    "make_spec_tools",
    "make_spec_callbacks",
    "make_doc_tools",
    "make_doc_callbacks",
    "make_prefab_tools",
    "make_prefab_callbacks",
]
