from senza_studio_components import registry


def test_get_tools_returns_callables_by_name():
    tools = registry.get_tools()
    assert set(tools) == {"db_query", "lookup_topic", "send_email"}
    assert all(callable(fn) for fn in tools.values())


def test_list_prefabs_returns_all_tools_and_empty_components():
    result = registry.list_prefabs()
    assert result["components"] == []
    names = {t["name"] for t in result["tools"]}
    assert names == {"db_query", "lookup_topic", "send_email"}
    # each entry carries enough for the meta-agent to decide + call bind_tool
    for tool in result["tools"]:
        assert "description" in tool
        assert "parameters" in tool


def test_list_prefabs_filters_by_kind():
    result = registry.list_prefabs(kind="tool")
    assert {t["name"] for t in result["tools"]} == {"db_query", "lookup_topic", "send_email"}
    result_none_kind = registry.list_prefabs(kind="component")
    assert result_none_kind["tools"] == []


def test_search_prefabs_matches_name_and_description():
    assert {r["name"] for r in registry.search_prefabs("email")} == {"send_email"}
    assert {r["name"] for r in registry.search_prefabs("sqlite")} == {"db_query"}
    assert {r["name"] for r in registry.search_prefabs("nonexistent_xyz")} == set()


def test_search_prefabs_empty_query_returns_nothing():
    assert registry.search_prefabs("") == []
    assert registry.search_prefabs("   ") == []


def test_recommend_prefabs_ranks_by_word_overlap():
    results = registry.recommend_prefabs("I need to notify a customer by email about their order")
    assert results, "expected at least one recommendation"
    assert results[0]["name"] == "send_email"


def test_recommend_prefabs_no_match_returns_empty():
    assert registry.recommend_prefabs("xyzzy plugh qwertyzzz") == []


def test_recommend_prefabs_ignores_generic_stopwords():
    """纯泛词（用户描述里必然出现但没有区分度的词）不该匹配到任何工具——
    否则描述写得越长的工具越容易靠噪声词蹭分。"""
    assert registry.recommend_prefabs("I need to use this for my workflow data") == []


def test_recommend_prefabs_name_match_outranks_longer_description():
    """回归测试：把 lookup_topic 的 description 写长之后，它一度靠泛词
    "need" 追平并（因为排序稳定、它在 PREFABS 里更靠前）挤掉了明显更该
    排第一的 send_email。name 命中要比 description 命中权重更高。"""
    results = registry.recommend_prefabs("send an email to notify the customer")
    assert results[0]["name"] == "send_email"


def test_recommend_prefabs_database_query_ranks_db_query_first():
    results = registry.recommend_prefabs("query rows from my sqlite database")
    assert results[0]["name"] == "db_query"
