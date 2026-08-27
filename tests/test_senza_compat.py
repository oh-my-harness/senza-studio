"""senza-sdk 兼容性回归测试。

不需要 LLM 调用——纯 AST + 运行时 introspection，见
scripts/check_senza_compat.py。跟其它 tests/test_*.py 一样是普通同步测试，
每次 `pytest` 都会自动跑，不需要额外标记。
"""
from scripts.check_senza_compat import discover_usages, main


def test_no_senza_api_drift():
    assert main() == 0


def test_discovers_a_nonzero_surface():
    # A sanity floor independent of main()'s own zero-usages guard: if the
    # AST scanner silently breaks (e.g. a future refactor changes how
    # agent.py imports/calls senza), this fails loudly instead of main()
    # reporting a misleadingly-green "no drift" over an empty usage set.
    usages = discover_usages()
    assert len(usages) >= 15
