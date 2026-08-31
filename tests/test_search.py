"""纯函数测 search 的参数归一化和 URL 构造。真浏览器路径走 e2e 验证，不进单测。"""
from __future__ import annotations

import pytest

from goofish_cli.commands.search.search import __test__ as t


def test_normalize_limit_clamps_and_defaults():
    normalize = t["_normalize_limit"]
    assert normalize(10) == 10
    assert normalize("5") == 5
    assert normalize(0) == 1
    assert normalize(-3) == 1
    assert normalize(999) == t["MAX_LIMIT"]
    assert normalize(None) == 20
    assert normalize("abc") == 20


def test_build_search_url_encodes_query():
    build = t["_build_search_url"]
    assert build("iPhone 15") == "https://www.goofish.com/search?q=iPhone%2015"
    assert build("中文") == "https://www.goofish.com/search?q=%E4%B8%AD%E6%96%87"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.goofish.com/item?id=123456&spm=foo", "123456"),
        ("https://www.goofish.com/item?spm=a&id=999", "999"),
        ("https://example.com/no-id", ""),
        ("", ""),
    ],
)
def test_item_id_from_url(url, expected):
    assert t["_item_id_from_url"](url) == expected


def test_auth_wall_attempts_is_two():
    """瞬时登录墙重试：总尝试 2 次（首次 + 1 次退避重试）。"""
    assert t["AUTH_WALL_ATTEMPTS"] == 2


def test_should_retry():
    """零卡片且 requiresAuth 为真才重试（瞬时登录墙兜底）。

    注意 `_EXTRACT_JS` 恒返回 `items` 键：真实登录墙载荷是
    `{"items": [], "requiresAuth": True, ...}`，必须重试。
    """
    should_retry = t["_should_retry"]
    assert should_retry({"items": [{"id": 1}]}) is False
    assert should_retry({}) is False
    assert should_retry({"requiresAuth": True}) is True
    assert should_retry({"requiresAuth": False}) is False
    assert should_retry({"items": [], "requiresAuth": True}) is True
    assert should_retry({"items": [], "requiresAuth": True, "empty": True}) is True
    assert should_retry({"items": [], "requiresAuth": True, "blocked": True}) is True
