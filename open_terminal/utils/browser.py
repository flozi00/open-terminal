"""Browser automation endpoints using Playwright.

Provides a session-based API for controlling a headless Chromium browser.
Each session gets its own browser context (isolated cookies, storage, etc.).

Requires the ``browser`` optional extra::

    pip install open-terminal[browser]
"""

import asyncio
import base64
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

_IDLE_TIMEOUT = 30 * 60  # 30 minutes

_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None


async def _ensure_browser() -> Browser:
    """Lazily launch the shared browser instance."""
    global _playwright, _browser
    if _browser is None or not _browser.is_connected():
        if _playwright is None:
            _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
    return _browser


class _Session:
    """Wraps a Playwright browser context + active page."""

    __slots__ = ("id", "context", "pages", "created_at", "last_used")

    def __init__(self, session_id: str, context: BrowserContext):
        self.id = session_id
        self.context = context
        self.pages: dict[str, Page] = {}
        self.created_at = time.time()
        self.last_used = time.time()

    def touch(self):
        self.last_used = time.time()

    async def get_page(self, page_id: Optional[str] = None) -> Page:
        """Return a page by ID, or the first page if not specified."""
        if page_id and page_id in self.pages:
            return self.pages[page_id]
        if not page_id and self.pages:
            return next(iter(self.pages.values()))
        raise KeyError("Page not found")


_sessions: dict[str, _Session] = {}
_cleanup_task: Optional[asyncio.Task] = None


async def _idle_cleanup_loop():
    """Periodically remove sessions idle for more than _IDLE_TIMEOUT."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        stale = [
            sid
            for sid, s in _sessions.items()
            if now - s.last_used > _IDLE_TIMEOUT
        ]
        for sid in stale:
            await _destroy_session(sid)


async def _destroy_session(session_id: str):
    session = _sessions.pop(session_id, None)
    if session:
        try:
            await session.context.close()
        except Exception:
            pass


def _ensure_cleanup_task():
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_idle_cleanup_loop())


def _get_session(session_id: str) -> _Session:
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Browser session not found")
    session.touch()
    return session


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    viewport_width: int = Field(1280, description="Browser viewport width in pixels.")
    viewport_height: int = Field(720, description="Browser viewport height in pixels.")
    user_agent: Optional[str] = Field(None, description="Custom User-Agent string.")


class NavigateRequest(BaseModel):
    url: str = Field(..., description="URL to navigate to.")
    wait_until: str = Field(
        "load",
        description="When to consider navigation complete: 'load', 'domcontentloaded', 'networkidle', or 'commit'.",
    )
    timeout: float = Field(30000, description="Navigation timeout in milliseconds.", ge=0, le=120000)


class ClickRequest(BaseModel):
    selector: str = Field(..., description="CSS or text selector for the element to click.")
    button: str = Field("left", description="Mouse button: 'left', 'right', or 'middle'.")
    click_count: int = Field(1, description="Number of clicks.", ge=1, le=3)
    timeout: float = Field(30000, description="Timeout in milliseconds.", ge=0, le=120000)


class TypeRequest(BaseModel):
    selector: str = Field(..., description="CSS selector for the input element.")
    text: str = Field(..., description="Text to type into the element.")
    delay: float = Field(0, description="Delay between key presses in milliseconds.", ge=0)
    clear: bool = Field(False, description="Clear the input before typing.")
    timeout: float = Field(30000, description="Timeout in milliseconds.", ge=0, le=120000)


class FillRequest(BaseModel):
    selector: str = Field(..., description="CSS selector for the input element.")
    value: str = Field(..., description="Value to fill into the element.")
    timeout: float = Field(30000, description="Timeout in milliseconds.", ge=0, le=120000)


class SelectOptionRequest(BaseModel):
    selector: str = Field(..., description="CSS selector for the <select> element.")
    values: list[str] = Field(..., description="Option value(s) to select.")
    timeout: float = Field(30000, description="Timeout in milliseconds.", ge=0, le=120000)


class EvaluateRequest(BaseModel):
    expression: str = Field(..., description="JavaScript expression to evaluate in the page context.")


class WaitForSelectorRequest(BaseModel):
    selector: str = Field(..., description="CSS selector to wait for.")
    state: str = Field(
        "visible",
        description="Wait for element to be 'attached', 'detached', 'visible', or 'hidden'.",
    )
    timeout: float = Field(30000, description="Timeout in milliseconds.", ge=0, le=120000)


class PressKeyRequest(BaseModel):
    key: str = Field(
        ...,
        description="Key to press, e.g. 'Enter', 'Tab', 'ArrowDown', 'Control+a'.",
    )
    selector: Optional[str] = Field(None, description="Optional CSS selector to focus before pressing.")
    timeout: float = Field(30000, description="Timeout in milliseconds.", ge=0, le=120000)


class HoverRequest(BaseModel):
    selector: str = Field(..., description="CSS selector for the element to hover over.")
    timeout: float = Field(30000, description="Timeout in milliseconds.", ge=0, le=120000)


class ScrollRequest(BaseModel):
    x: int = Field(0, description="Horizontal scroll amount in pixels.")
    y: int = Field(0, description="Vertical scroll amount in pixels.")
    selector: Optional[str] = Field(
        None, description="CSS selector of scrollable element. Defaults to the page."
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def create_browser_router(verify_api_key) -> APIRouter:
    """Create the browser automation router with the given auth dependency."""

    router = APIRouter(
        prefix="/browser",
        tags=["browser"],
        dependencies=[Depends(verify_api_key)],
    )

    # -- Session management -------------------------------------------------

    @router.post(
        "",
        operation_id="create_browser_session",
        summary="Create a browser session",
        description="Launch a new headless browser context with its own cookies and storage. Returns a session ID.",
    )
    async def create_session(req: CreateSessionRequest = CreateSessionRequest()):
        _ensure_cleanup_task()

        try:
            browser = await _ensure_browser()
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to launch browser: {e}",
            )

        context_opts: dict = {
            "viewport": {"width": req.viewport_width, "height": req.viewport_height},
        }
        if req.user_agent:
            context_opts["user_agent"] = req.user_agent

        context = await browser.new_context(**context_opts)
        page = await context.new_page()

        session_id = uuid.uuid4().hex[:12]
        session = _Session(session_id, context)

        page_id = uuid.uuid4().hex[:8]
        session.pages[page_id] = page

        _sessions[session_id] = session

        return {
            "id": session_id,
            "page_id": page_id,
            "status": "ready",
        }

    @router.get(
        "/{session_id}",
        operation_id="get_browser_session",
        summary="Get browser session status",
        description="Return session info including open pages.",
    )
    async def get_session(session_id: str):
        session = _get_session(session_id)
        pages = []
        for pid, page in session.pages.items():
            pages.append({
                "id": pid,
                "url": page.url,
                "title": await page.title(),
            })
        return {
            "id": session.id,
            "pages": pages,
            "status": "ready",
        }

    @router.delete(
        "/{session_id}",
        operation_id="close_browser_session",
        summary="Close a browser session",
        description="Close all pages and release resources for this session.",
    )
    async def close_session(session_id: str):
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail="Browser session not found")
        await _destroy_session(session_id)
        return {"status": "closed"}

    # -- Page management ----------------------------------------------------

    @router.post(
        "/{session_id}/pages",
        operation_id="create_browser_page",
        summary="Open a new page (tab)",
        description="Create a new page in the browser session. Returns the page ID.",
    )
    async def create_page(session_id: str):
        session = _get_session(session_id)
        page = await session.context.new_page()
        page_id = uuid.uuid4().hex[:8]
        session.pages[page_id] = page
        return {"page_id": page_id, "url": page.url}

    @router.delete(
        "/{session_id}/pages/{page_id}",
        operation_id="close_browser_page",
        summary="Close a page (tab)",
        description="Close a specific page within the browser session.",
    )
    async def close_page(session_id: str, page_id: str):
        session = _get_session(session_id)
        page = session.pages.pop(page_id, None)
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        await page.close()
        return {"status": "closed"}

    # -- Navigation ---------------------------------------------------------

    @router.post(
        "/{session_id}/navigate",
        operation_id="browser_navigate",
        summary="Navigate to a URL",
        description="Navigate a page to the specified URL and wait for it to load.",
    )
    async def navigate(session_id: str, req: NavigateRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            response = await page.goto(
                req.url,
                wait_until=req.wait_until,
                timeout=req.timeout,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "url": page.url,
            "title": await page.title(),
            "status": response.status if response else None,
        }

    @router.post(
        "/{session_id}/back",
        operation_id="browser_go_back",
        summary="Go back",
        description="Navigate the page back in history.",
    )
    async def go_back(session_id: str, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")
        await page.go_back()
        return {"url": page.url, "title": await page.title()}

    @router.post(
        "/{session_id}/forward",
        operation_id="browser_go_forward",
        summary="Go forward",
        description="Navigate the page forward in history.",
    )
    async def go_forward(session_id: str, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")
        await page.go_forward()
        return {"url": page.url, "title": await page.title()}

    @router.post(
        "/{session_id}/reload",
        operation_id="browser_reload",
        summary="Reload the page",
        description="Reload the current page.",
    )
    async def reload(session_id: str, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")
        await page.reload()
        return {"url": page.url, "title": await page.title()}

    # -- Interaction --------------------------------------------------------

    @router.post(
        "/{session_id}/click",
        operation_id="browser_click",
        summary="Click an element",
        description="Click on an element matching the given selector.",
    )
    async def click(session_id: str, req: ClickRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            await page.click(
                req.selector,
                button=req.button,
                click_count=req.click_count,
                timeout=req.timeout,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"status": "ok", "url": page.url}

    @router.post(
        "/{session_id}/type",
        operation_id="browser_type",
        summary="Type text into an element",
        description="Type text into an input element character by character. Use fill for instant value setting.",
    )
    async def type_text(session_id: str, req: TypeRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            if req.clear:
                await page.fill(req.selector, "", timeout=req.timeout)
            await page.type(req.selector, req.text, delay=req.delay, timeout=req.timeout)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"status": "ok"}

    @router.post(
        "/{session_id}/fill",
        operation_id="browser_fill",
        summary="Fill an input element",
        description="Set the value of an input element instantly (clears existing value first).",
    )
    async def fill(session_id: str, req: FillRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            await page.fill(req.selector, req.value, timeout=req.timeout)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"status": "ok"}

    @router.post(
        "/{session_id}/select",
        operation_id="browser_select_option",
        summary="Select dropdown option(s)",
        description="Select one or more options in a <select> element by value.",
    )
    async def select_option(session_id: str, req: SelectOptionRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            selected = await page.select_option(req.selector, req.values, timeout=req.timeout)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"selected": selected}

    @router.post(
        "/{session_id}/hover",
        operation_id="browser_hover",
        summary="Hover over an element",
        description="Move the mouse over an element matching the selector.",
    )
    async def hover(session_id: str, req: HoverRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            await page.hover(req.selector, timeout=req.timeout)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"status": "ok"}

    @router.post(
        "/{session_id}/press",
        operation_id="browser_press_key",
        summary="Press a keyboard key",
        description="Press a key or key combination (e.g. 'Enter', 'Control+a').",
    )
    async def press_key(session_id: str, req: PressKeyRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            if req.selector:
                await page.press(req.selector, req.key, timeout=req.timeout)
            else:
                await page.keyboard.press(req.key)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"status": "ok"}

    @router.post(
        "/{session_id}/scroll",
        operation_id="browser_scroll",
        summary="Scroll the page or an element",
        description="Scroll by the specified pixel amounts. Positive y scrolls down.",
    )
    async def scroll(session_id: str, req: ScrollRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        if req.selector:
            await page.eval_on_selector(
                req.selector,
                f"el => el.scrollBy({req.x}, {req.y})",
            )
        else:
            await page.evaluate(f"window.scrollBy({req.x}, {req.y})")

        return {"status": "ok"}

    @router.post(
        "/{session_id}/wait",
        operation_id="browser_wait_for_selector",
        summary="Wait for an element",
        description="Wait until an element matching the selector reaches the desired state.",
    )
    async def wait_for_selector(
        session_id: str, req: WaitForSelectorRequest, page_id: Optional[str] = Query(None)
    ):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            await page.wait_for_selector(req.selector, state=req.state, timeout=req.timeout)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"status": "ok", "selector": req.selector, "state": req.state}

    # -- Content extraction -------------------------------------------------

    @router.post(
        "/{session_id}/evaluate",
        operation_id="browser_evaluate",
        summary="Evaluate JavaScript",
        description="Execute a JavaScript expression in the page and return the result.",
    )
    async def evaluate(session_id: str, req: EvaluateRequest, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            result = await page.evaluate(req.expression)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"result": result}

    @router.get(
        "/{session_id}/content",
        operation_id="browser_get_content",
        summary="Get page HTML content",
        description="Return the full HTML content of the page.",
    )
    async def get_content(session_id: str, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        content = await page.content()
        return {
            "url": page.url,
            "title": await page.title(),
            "content": content,
        }

    @router.get(
        "/{session_id}/text",
        operation_id="browser_get_text",
        summary="Get page text content",
        description="Return the visible text content of the page (strips HTML tags). Useful for reading page content without markup.",
    )
    async def get_text(session_id: str, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        text = await page.evaluate("() => document.body.innerText")
        return {
            "url": page.url,
            "title": await page.title(),
            "text": text,
        }

    @router.get(
        "/{session_id}/screenshot",
        operation_id="browser_screenshot",
        summary="Take a screenshot",
        description="Capture a screenshot of the page as a base64-encoded PNG.",
    )
    async def screenshot(
        session_id: str,
        page_id: Optional[str] = Query(None),
        full_page: bool = Query(False, description="Capture the full scrollable page."),
        selector: Optional[str] = Query(None, description="CSS selector to screenshot a specific element."),
    ):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            if selector:
                element = await page.query_selector(selector)
                if not element:
                    raise HTTPException(status_code=404, detail="Element not found")
                raw = await element.screenshot(type="png")
            else:
                raw = await page.screenshot(type="png", full_page=full_page)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "url": page.url,
            "image": base64.b64encode(raw).decode("ascii"),
            "format": "png",
        }

    @router.get(
        "/{session_id}/pdf",
        operation_id="browser_pdf",
        summary="Generate PDF",
        description="Generate a PDF of the current page. Returns base64-encoded PDF data.",
    )
    async def generate_pdf(session_id: str, page_id: Optional[str] = Query(None)):
        session = _get_session(session_id)
        try:
            page = await session.get_page(page_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Page not found")

        try:
            raw = await page.pdf()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "url": page.url,
            "data": base64.b64encode(raw).decode("ascii"),
            "format": "pdf",
        }

    # -- Cookie management --------------------------------------------------

    @router.get(
        "/{session_id}/cookies",
        operation_id="browser_get_cookies",
        summary="Get cookies",
        description="Return all cookies in the browser context.",
    )
    async def get_cookies(session_id: str):
        session = _get_session(session_id)
        cookies = await session.context.cookies()
        return {"cookies": cookies}

    @router.delete(
        "/{session_id}/cookies",
        operation_id="browser_clear_cookies",
        summary="Clear cookies",
        description="Remove all cookies from the browser context.",
    )
    async def clear_cookies(session_id: str):
        session = _get_session(session_id)
        await session.context.clear_cookies()
        return {"status": "ok"}

    return router
