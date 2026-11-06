"""Shared FastHTML UI components and layout."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from fasthtml.common import (
    A,
    Body,
    Button,
    Div,
    Footer,
    Head,
    Html,
    Li,
    Link,
    Main,
    Meta,
    NotStr,
    Script,
    Small,
    Style,
    Title,
    Ul,
)
from fasthtml.components import FT
from fastlucide.icons import Sun_moon, spritesheet

_APP_DIR = Path(__file__).parent


@dataclass(frozen=True)
class PageInfo:
    """One tool page: what the nav shows and what the tab title says.

    The key is the value views pass to `page()` as `active`; it doubles as
    the registry lookup. `title` is a full tab title (suffix appended
    automatically). External links (Portfolio, Blog…) do not belong here —
    they are not pages of this app.
    """

    key: str
    label: str
    href: str
    title: str


# Every page of this app, in nav order. Adding a page = adding one entry
# here and a view that calls `page("<key>", ...)`.
_PAGES: dict[str, PageInfo] = {
    entry.key: entry
    for entry in (
        PageInfo("home", "Tools", "/", "Tools"),
        PageInfo("jp-reader", "JP Reader", "/jp-reader/", "JP Reader"),
        PageInfo("jp-translator", "JP Translator", "/jp-translator/", "JP Translator"),
    )
}

# Appended to every page's tab title; the home page claims the bare name.
_TITLE_SUFFIX = " · Work Utilities"

# Build stamp: the newest mtime of any file the app serves or renders. It
# changes whenever the code changes, so a page refresh both shows which
# build you are on and cache-busts every asset — no manual version bumps.
_BUILD_STAMP: str | None = None
_BUILD_TIME: str | None = None


def build_stamp() -> str:
    """A short hash of the current build, stable across requests."""
    global _BUILD_STAMP
    if _BUILD_STAMP is None:
        mtimes = [
            path.stat().st_mtime
            for path in _APP_DIR.rglob("*")
            if path.suffix in (".py", ".js") and "__pycache__" not in path.parts
        ]
        digest = sha256(str(max(mtimes)).encode()).hexdigest()
        _BUILD_STAMP = digest[:7]
    return _BUILD_STAMP


def build_time() -> str:
    """When the current build was made, as a human-readable UTC stamp.

    The latest code always has the newest mtime, so this tells a user at a
    glance whether the page they see predates a deploy.
    """
    global _BUILD_TIME
    if _BUILD_TIME is None:
        mtimes = [
            path.stat().st_mtime
            for path in _APP_DIR.rglob("*")
            if path.suffix in (".py", ".js") and "__pycache__" not in path.parts
        ]
        _BUILD_TIME = datetime.fromtimestamp(max(mtimes), tz=UTC).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    return _BUILD_TIME


def asset_url(path: str) -> str:
    """A static asset URL with the build stamp as its cache-buster."""
    return f"{path}?v={build_stamp()}"


def update_banner():
    """A hidden 'update available' notice the client JS can reveal.

    The page embeds its own build stamp; a small script polls /build and
    compares. When they differ, a newer build is serving and a refresh
    will pick it up — the same signal a PWA gives, for a server-rendered
    page.
    """
    return NotStr(
        f"<div id='update-banner' role='status' "
        f"data-build='{build_stamp()}' "
        f"class='hidden fixed bottom-4 left-1/2 -translate-x-1/2 z-50 "
        f"alert alert-info shadow-lg'>"
        "Update available — <button id='update-refresh' "
        "class='link link-primary'>Refresh</button></div>"
    )


def page_title(active: str, title: str | None = None) -> str:
    """The tab title for a page: its own name plus the site name.

    `title` overrides the registry name — for pages that vary per record,
    pass the record's own title. Falls back to the bare site name for an
    unknown key.
    """
    info = _PAGES.get(active)
    if title:
        return f"{title}{_TITLE_SUFFIX}"
    if info:
        return f"{info.title}{_TITLE_SUFFIX}"
    return "Work Utilities"


def _nav(active: str) -> FT:
    """The in-app links, built from the page registry."""
    links = [
        Li(
            A(
                info.label,
                href=info.href,
                cls="font-bold" if active == info.key else None,
            )
        )
        for info in _PAGES.values()
    ]
    # Sites that are not pages of this app stay outside the registry. They
    # tuck into a CSS-only dropdown (daisyUI focus method, no JS) so they
    # read as "other apps by the author" rather than sibling nav items. The
    # bare trigger div inherits the menu-item look from the wrapping menu,
    # and the li keeps the separator border the external links used to sit
    # behind.
    links.append(
        Li(
            Div(
                Div("More apps ▾", tabindex="0", role="button"),
                Ul(
                    Li(A("Portfolio", href="https://jeremiaaxel.dev")),
                    Li(A("Blog", href="https://blog.jeremiaaxel.dev")),
                    Li(
                        A(
                            "Money Backward",
                            href="https://moneybackward.jeremiaaxel.dev",
                        )
                    ),
                    tabindex="0",
                    cls=(
                        "dropdown-content z-50 menu bg-base-100 "
                        "rounded-box w-44 p-2 shadow"
                    ),
                ),
                cls="dropdown dropdown-end",
            ),
            cls="menu-horizontal border-l border-base-300 pl-2 ml-2",
        )
    )
    return Ul(*links, cls="menu menu-horizontal px-1")


def page(active: str, *content, title: str | None = None, wide: bool = False) -> FT:
    """Full HTML page with DaisyUI + htmx.

    `active` is the page's registry key: it highlights the nav link and
    picks the tab title. `title` overrides the registry tab title. `wide`
    lets a page use the desktop's full width — for layouts that put
    primary and secondary content side by side; the default keeps the
    reading column narrow.
    """
    return Html(
        Head(
            Meta(charset="UTF-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1.0"),
            Title(page_title(active, title)),
            Link(rel="stylesheet", href="https://cdn.jsdelivr.net/npm/daisyui@5"),
            Script(src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"),
            Script(src="https://unpkg.com/htmx.org@1.9.12"),
            Style("rt { font-size: 0.5em; }"),
            # Theme before first paint: the stored choice, else the OS
            # preference. Inline so a dark-mode visitor never sees a white
            # flash; theme.js only handles clicks after that.
            NotStr(
                "<script>"
                "(function(){try{var t=localStorage.getItem('theme');"
                "if(t!=='light'&&t!=='dark')?"
                "t=matchMedia('(prefers-color-scheme: dark)').matches"
                "? 'dark':'light':0;"
                "if(t)document.documentElement.setAttribute('data-theme',t);}"
                "catch(e){}})();"
                "</script>"
            ),
        ),
        Body(
            Div(
                Div(
                    A("Work Utilities", href="/", cls="btn btn-ghost text-xl"),
                    cls="flex-1",
                ),
                Div(_nav(active), cls="flex-none"),
                Button(
                    Sun_moon(sz=18),
                    type="button",
                    id="theme-toggle",
                    title="Switch between light and dark",
                    aria_label="Toggle dark mode",
                    cls="btn btn-ghost btn-sm btn-square flex-none",
                ),
                cls="navbar bg-base-100 shadow-sm",
            ),
            Main(
                *content,
                cls=(
                    "container mx-auto px-4 py-8 max-w-4xl" if not wide
                    else "container mx-auto px-4 py-8 max-w-7xl"
                ),
            ),
            Footer(
                Small(
                    f"build {build_stamp()} · {build_time()}",
                    title="When this page's code was last changed",
                    cls="opacity-40",
                ),
                cls="footer footer-center pb-4 text-base-content",
            ),
            update_banner(),
            Script(src=asset_url("/app.js")),
            Script(src=asset_url("/theme.js")),
            # Every icon on the site is a fastlucide `<use>` pointing into this
            # sheet, so it has to be on every page — including the icons that
            # arrive later in a swapped-in fragment or are drawn by JavaScript.
            spritesheet,
            cls="min-h-screen",
        ),
        lang="en",
    )
