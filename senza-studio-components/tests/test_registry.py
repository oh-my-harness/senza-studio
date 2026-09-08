from senza_studio_components import registry


def test_get_tools_returns_callables_by_name():
    tools = registry.get_tools()
    assert set(tools) == {"db_query", "lookup_topic", "send_email"}
    assert all(callable(fn) for fn in tools.values())


def test_list_prefabs_returns_both_families():
    result = registry.list_prefabs()
    names = {t["name"] for t in result["tools"]}
    assert names == {"db_query", "lookup_topic", "send_email"}
    # 能力组件从 Phase 4 切片二起不再是空列表（详见 test_components.py）
    assert {c["name"] for c in result["components"]} == {
        "approval_flow",
        "approval_with_notice",
    }
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
    # "email" 同时命中 send_email 工具和会发通知邮件的 approval_with_notice
    # 组件——搜索横跨两个族是有意的，元 agent 描述需求时不知道该找工具还是
    # 找组件，让它两边都能搜到才对。
    assert {r["name"] for r in registry.search_prefabs("email")} == {
        "send_email",
        "approval_with_notice",
    }
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


# ── 中文检索 ─────────────────────────────────────────────


def test_recommend_matches_chinese_descriptions():
    """Studio 的用户用中文描述需求，元 agent 转述时也常常直接用中文调
    recommend_prefabs。_WORD_RE 是 [a-z0-9_]+，中文一个词都切不出来——没有
    人工检索词这一层的话，"需要有人工审批" 返回的是空列表（亲测），整条
    "推荐预制件"的路径对中文用户等于不存在。
    """
    assert [r["name"] for r in registry.recommend_prefabs("需要有人工审批这一步")] == [
        "approval_flow",
        "approval_with_notice",
    ]
    assert registry.recommend_prefabs("查数据库里的订单")[0]["name"] == "db_query"
    assert registry.recommend_prefabs("发邮件通知客户")[0]["name"] == "send_email"


def test_search_matches_chinese_keywords():
    assert {r["name"] for r in registry.search_prefabs("审批")} == {
        "approval_flow",
        "approval_with_notice",
    }
    assert "send_email" in {r["name"] for r in registry.search_prefabs("邮件")}


def test_english_keyword_matching_stays_whole_word():
    """英文检索词仍走整词匹配——退回子串匹配的话，"need" 会命中 "needed"
    这类误匹配又会回来（slice 1 修过一次）。"""
    assert registry.recommend_prefabs("hum") == []      # "human" 的前缀不该命中
    assert registry.recommend_prefabs("a human decision")[0]["kind"] == "component"


def test_keywords_are_not_exposed_to_the_model():
    """检索词是给检索用的，不该占模型的 context。"""
    for tool in registry.list_prefabs()["tools"]:
        assert "keywords" not in tool
    for component in registry.list_prefabs()["components"]:
        assert "keywords" not in component
