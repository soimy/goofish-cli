"""browser.py 纯函数：cookie 双域注入。

背景（2026-08 探针实测）：按名字单域分发时 unb/tracknick/tfstk/xlly_s 等会话
cookie 全落 .goofish.com，www.goofish.com 页面判定"未登录"（匿名态偶发登录墙）。
修复为每个 cookie 双域各注入一份，对齐真实浏览器里淘系双域都落 cookie 的形态。
"""
from __future__ import annotations

from goofish_cli.core.browser import _COOKIE_DOMAINS, _cookies_to_playwright


def test_dual_domain_injection_covers_both_domains():
    out = _cookies_to_playwright({"unb": "123"})
    assert {(c["name"], c["domain"]) for c in out} == {
        ("unb", ".taobao.com"),
        ("unb", ".goofish.com"),
    }


def test_dual_domain_injection_skips_empty_values():
    out = _cookies_to_playwright({"unb": "123", "empty_one": ""})
    assert {c["name"] for c in out} == {"unb"}


def test_dual_domain_injection_cookie_attrs():
    out = _cookies_to_playwright({"_m_h5_tk": "abc_def"})
    assert len(out) == len(_COOKIE_DOMAINS)
    for c in out:
        assert c["path"] == "/"
        assert c["secure"] is True
        assert c["httpOnly"] is False
        assert c["sameSite"] == "None"
        assert c["expires"] > 0
