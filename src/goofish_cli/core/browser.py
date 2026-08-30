"""Playwright 浏览器上下文 —— 吸纳 OpenCLI 的浏览器自动化路线。

设计要点（用户明确要求）：
1. **用系统 Chrome**（`channel="chrome"`），不用 playwright 自带的 bundled chromium——
   bundled chromium 的 UA / CDP 指纹太"裸"，是风控高危目标；系统 Chrome 是真实用户
   每天在用的可执行，配上真实 cookies 后基本等同正常浏览。
2. **每次调用独立 profile**（`~/.goofish-cli/profiles/chrome-<tmp>/`）：Chrome 一个
   `user_data_dir` 同时只能被一个进程打开（`SingletonLock`），固定路径会让并发调用
   （MCP 同时跑多个 tool / 用户手动并发）直接 ProfileInUse 起不来。所以每次 tmp 一个
   profile，退出清理——代价是首次启动多几百 ms，收益是天然支持并发。登录态不需要靠
   profile 持久化，我们每次用 `add_cookies` 从 `Session.load()` 灌。cookie 来源复用
   `Session.load()` 的三级兜底 —— `cookies.json` → `browser_cookie3` 自动从本机
   Chrome 抓 → `AuthRequiredError`，不在这里重复实现。
3. **默认 headful**：实测 headless chrome 的指纹（即便 channel=chrome）仍会被闲鱼判
   「非法访问」，返回"请使用正常浏览器访问"。要通过就必须以窗口模式启动。CI / 无桌面
   场景可 `GOOFISH_HEADLESS=1` 切回 headless（代价是可能被风控）。

同步命令怎么用：用 `asyncio.run(...)` 驱动本模块的 async 上下文（参考 list_chats
`--watch-secs` 的 `asyncio.run(collect_session_cids(...))` 模式）。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from loguru import logger

from goofish_cli.core.session import Session

PROFILES_PARENT = Path.home() / ".goofish-cli" / "profiles"

# 需要种的域。淘系签名链路（_m_h5_tk / x5sec / sgcookie / cookie2）历史上跨
# .taobao.com，而 www.goofish.com 页面自己的登录态判定读的是 .goofish.com 域上的
# 会话 cookie（unb / tracknick / tfstk / xlly_s 等）。
# 实测（2026-08 探针）：按名字单域分发时，16 个会话 cookie 全落 .goofish.com、
# 页面导航栏仍显示"登录"（匿名态偶发整页登录墙）；把全部 cookie 同时种到两个域
# （对齐真实浏览器里淘系双域都落 cookie 的形态）后页面恢复登录态，搜索稳定出卡片。
# 浏览器发请求时本就只带 host 匹配的 cookie，双域冗余无害。
_COOKIE_DOMAINS = (".taobao.com", ".goofish.com")


def _cookies_to_playwright(cookies: dict[str, str]) -> list[dict[str, Any]]:
    """把 `{name: value}` 转成 playwright `add_cookies` 需要的列表形态。

    每个 cookie 双域各注入一份：浏览器发请求时按 host 匹配自动挑选，
    规避"按名字猜域"单域分发导致的页面登录态判定失败。
    """
    now = int(__import__("time").time())
    # 7 天后过期——cookies.json 自身会被 Session 层更新，这里只要够跑完当前命令就行
    expires = now + 7 * 24 * 3600
    out: list[dict[str, Any]] = []
    for name, value in cookies.items():
        if not value:
            continue
        for domain in _COOKIE_DOMAINS:
            out.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "expires": expires,
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            })
    return out


def _load_cookies_from_session() -> dict[str, str]:
    """直接走 Session.load —— 三级兜底 (cookies.json → 本机 Chrome 自动抓 → AuthRequiredError)
    全在 Session 层已经实现，不重复造轮子。拿到 http.cookies 之后展平成 {name: value}。
    """
    session = Session.load()
    return {name: value for name, value in session.http.cookies.items() if value}


@asynccontextmanager
async def goofish_page(
    *,
    headless: bool | None = None,
    viewport: tuple[int, int] = (1440, 900),
    cookies: dict[str, str] | None = None,
) -> AsyncIterator[Any]:
    """启动系统 Chrome（独立 tmp profile）+ 灌 cookie，yield 出一个 `Page`。

    `cookies` 可选：显式传入 `{name: value}` 时直接用；不传则走 `Session.load()`
    三级兜底。自动刷 `_m_h5_tk` 的调用方需要用内存里当前 session 的 cookies 而非
    磁盘快照（可能已被改）—— 传 `cookies=session.http.cookies` 展平后的 dict。

    用法：
        async with goofish_page() as page:
            await page.goto("https://www.goofish.com/search?q=foo")
            ...
    """
    from playwright.async_api import async_playwright

    if headless is None:
        # 默认 headful。CI 用户显式 GOOFISH_HEADLESS=1 切回（可能触发风控）。
        headless = os.environ.get("GOOFISH_HEADLESS") == "1"

    PROFILES_PARENT.mkdir(parents=True, exist_ok=True)
    # 每次调用独立 profile 目录，避开 Chrome SingletonLock 并发冲突
    profile_dir = Path(tempfile.mkdtemp(prefix="chrome-", dir=str(PROFILES_PARENT)))
    if cookies is None:
        cookies = _load_cookies_from_session()
    pw_cookies = _cookies_to_playwright(cookies)

    try:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel="chrome",
                headless=headless,
                viewport={"width": viewport[0], "height": viewport[1]},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                    "--no-first-run",
                ],
            )
            try:
                await context.add_cookies(pw_cookies)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"注入 cookie 失败：{e}")

            page = context.pages[0] if context.pages else await context.new_page()
            # 隐藏 webdriver 特征（CDP 检测 cookie 外的最后一道门）
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            try:
                yield page
            finally:
                await context.close()
    finally:
        # 清理 tmp profile。忽略错误（进程被 kill 时残留目录由用户手动清 ~/.goofish-cli/profiles/）
        shutil.rmtree(profile_dir, ignore_errors=True)


async def auto_scroll(page: Any, times: int = 2, pause_ms: int = 800) -> None:
    """模拟 OpenCLI 的 `page.autoScroll({times})`：滚到底 N 次触发懒加载。"""
    for _ in range(times):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(pause_ms)
    await page.evaluate("window.scrollTo(0, 0)")
