"""纯函数测 search 的参数归一化和 URL 构造。真浏览器路径走 e2e 验证，不进单测。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from goofish_cli.commands.search.search import __test__ as t
from goofish_cli.commands.search.search import search


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


def test_search_returns_ranked_items_on_success():
    """回归：_run() 成功时应返回带 rank/item_id 的 list，不能是 None。

    patch `_search_once`（而非 `asyncio.run`），让 `_run` 真正执行，
    验证 rank/item_id 组装逻辑。
    """
    from unittest.mock import patch

    fake_raw = {
        "items": [
            {"title": "商品A", "url": "https://www.goofish.com/item?id=100", "price": "¥10"},
            {"title": "商品B", "url": "https://www.goofish.com/item?id=200", "price": "¥20"},
        ],
        "requiresAuth": False,
        "blocked": False,
        "empty": False,
        "bodyPreview": "",
    }
    with patch("goofish_cli.commands.search.search._search_once", new=AsyncMock(return_value=fake_raw)):
        result = search("test")
    assert result is not None
    assert result["total"] == 2
    assert result["items"][0]["rank"] == 1
    assert result["items"][0]["item_id"] == "100"
    assert result["items"][1]["rank"] == 2
    assert result["items"][1]["item_id"] == "200"


def test_search_returns_none_when_run_returns_none():
    """_run 返回 None 时 search() 原样透传——这是真 bug，应当让上层注意到。"""
    with patch("asyncio.run", return_value=None):
        result = search("test")
    assert result is None
