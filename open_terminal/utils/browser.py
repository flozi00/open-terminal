"""Browser automation endpoints using Playwright.

Provides a minimal, agent-friendly API for controlling a headless Chromium
browser.  Tools are designed so that LLM agents never need to construct CSS
selectors — they discover page content via text extraction and link/form
introspection, then interact using visible labels.

For edge cases not covered by the high-level tools, ``browser_evaluate``
allows executing arbitrary JavaScript.

Requires the ``browser`` optional extra::

    pip install open-terminal[browser]
"""

import asyncio
import os
import tempfile
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
    """Wraps a Playwright browser context + its single page."""

    __slots__ = ("id", "context", "page", "created_at", "last_used")

    def __init__(self, session_id: str, context: BrowserContext, page: Page):
        self.id = session_id
        self.context = context
        self.page = page
        self.created_at = time.time()
        self.last_used = time.time()

    def touch(self):
        self.last_used = time.time()


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


class NavigateRequest(BaseModel):
    url: str = Field(..., description="URL to navigate to.")
    wait_until: str = Field(
        "load",
        description="When to consider navigation complete: 'load', 'domcontentloaded', 'networkidle', or 'commit'.",
    )


class FillFormRequest(BaseModel):
    fields: dict[str, str] = Field(
        ...,
        description=(
            "Map of field label/name/placeholder to value. "
            "Example: {\"Username\": \"john\", \"Password\": \"secret\"}. "
            "Use browser_get_form_fields to discover available fields first."
        ),
    )
    submit: bool = Field(
        False,
        description="Press Enter on the last field after filling to submit the form.",
    )


class EvaluateRequest(BaseModel):
    expression: str = Field(..., description="JavaScript expression to evaluate in the page context.")


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
        description=(
            "Launch a new headless browser context with its own cookies and storage. "
            "Returns a session_id to use with all other browser tools."
        ),
    )
    async def create_session(
        viewport_width: int = Query(1280, description="Browser viewport width in pixels."),
        viewport_height: int = Query(720, description="Browser viewport height in pixels."),
        user_agent: Optional[str] = Query(None, description="Custom User-Agent string."),
    ):
        _ensure_cleanup_task()

        try:
            browser = await _ensure_browser()
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to launch browser: {e}",
            )

        context_opts: dict = {
            "viewport": {"width": viewport_width, "height": viewport_height},
        }
        if user_agent:
            context_opts["user_agent"] = user_agent

        context = await browser.new_context(**context_opts)
        page = await context.new_page()

        session_id = uuid.uuid4().hex[:12]
        session = _Session(session_id, context, page)
        _sessions[session_id] = session

        return {
            "session_id": session_id,
            "status": "ready",
        }

    @router.delete(
        "/{session_id}",
        operation_id="close_browser_session",
        summary="Close a browser session",
        description="Close the browser and release all resources for this session.",
    )
    async def close_session(session_id: str):
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail="Browser session not found")
        await _destroy_session(session_id)
        return {"status": "closed"}

    # -- Navigation ---------------------------------------------------------

    @router.post(
        "/{session_id}/navigate",
        operation_id="browser_navigate",
        summary="Navigate to a URL",
        description=(
            "Navigate to the specified URL and wait for the page to load. "
            "After navigating, use browser_get_text to read content or browser_get_links to discover links."
        ),
    )
    async def navigate(session_id: str, req: NavigateRequest):
        session = _get_session(session_id)
        page = session.page

        try:
            response = await page.goto(req.url, wait_until=req.wait_until, timeout=30000)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "url": page.url,
            "title": await page.title(),
            "status": response.status if response else None,
        }

    # -- Content reading ----------------------------------------------------

    @router.get(
        "/{session_id}/text",
        operation_id="browser_get_text",
        summary="Get page text content",
        description=(
            "Return the visible text of the page (no HTML). "
            "This is the primary way to read page content."
        ),
    )
    async def get_text(session_id: str):
        session = _get_session(session_id)
        page = session.page
        text = await page.evaluate("() => document.body.innerText")
        return {
            "url": page.url,
            "title": await page.title(),
            "text": text,
        }

    @router.get(
        "/{session_id}/links",
        operation_id="browser_get_links",
        summary="Get all links on the page",
        description=(
            "Extract all clickable links from the page with their visible text and URL. "
            "Use this to discover navigation targets instead of guessing URLs. "
            "Then use browser_click_link to click by text, or browser_navigate with the URL."
        ),
    )
    async def get_links(
        session_id: str,
        selector: Optional[str] = Query(
            None,
            description="Optional CSS selector to scope the search (e.g. 'nav', '#sidebar').",
        ),
    ):
        session = _get_session(session_id)
        page = session.page

        js = """
        (scope) => {
            const root = scope ? document.querySelector(scope) : document;
            if (!root) return [];
            const anchors = root.querySelectorAll('a[href]');
            const seen = new Set();
            const results = [];
            for (const a of anchors) {
                const text = a.innerText.trim().substring(0, 200);
                const href = a.href;
                const key = text + '|' + href;
                if (!text || seen.has(key)) continue;
                seen.add(key);
                results.push({text, href});
            }
            return results;
        }
        """
        try:
            links = await page.evaluate(js, selector)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "url": page.url,
            "count": len(links),
            "links": links,
        }

    @router.get(
        "/{session_id}/form_fields",
        operation_id="browser_get_form_fields",
        summary="Get all form fields on the page",
        description=(
            "Discover all fillable form fields (inputs, textareas, selects) with their "
            "labels, types, placeholders, and current values. "
            "Use this before browser_fill_form to know what fields are available."
        ),
    )
    async def get_form_fields(session_id: str):
        session = _get_session(session_id)
        page = session.page

        js = """
        () => {
            const fields = [];
            const inputs = document.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="image"]), textarea, select'
            );
            for (const el of inputs) {
                const id = el.id;
                const name = el.name;
                const type = el.type || el.tagName.toLowerCase();
                const placeholder = el.placeholder || '';
                const value = el.value || '';
                const ariaLabel = el.getAttribute('aria-label') || '';

                // Find associated label
                let label = '';
                if (id) {
                    const labelEl = document.querySelector(`label[for="${id}"]`);
                    if (labelEl) label = labelEl.innerText.trim();
                }
                if (!label) {
                    const parent = el.closest('label');
                    if (parent) label = parent.innerText.trim();
                }

                // For <select>, collect options
                let options = [];
                if (el.tagName === 'SELECT') {
                    options = Array.from(el.options).map(o => ({
                        value: o.value,
                        text: o.text.trim(),
                        selected: o.selected,
                    }));
                }

                // Best human-readable identifier for the field
                const identifier = label || ariaLabel || placeholder || name || id || '';

                fields.push({
                    identifier,
                    type,
                    name: name || '',
                    placeholder,
                    value,
                    options: options.length ? options : undefined,
                    required: el.required || false,
                });
            }
            return fields;
        }
        """
        try:
            fields = await page.evaluate(js)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "url": page.url,
            "count": len(fields),
            "fields": fields,
        }

    @router.get(
        "/{session_id}/buttons",
        operation_id="browser_get_buttons",
        summary="Get all buttons on the page",
        description=(
            "Discover all clickable buttons on the page with their visible text. "
            "Use this before browser_click_button to know what buttons are available."
        ),
    )
    async def get_buttons(session_id: str):
        session = _get_session(session_id)
        page = session.page

        js = """
        () => {
            const results = [];
            const seen = new Set();
            const els = document.querySelectorAll(
                'button, input[type="submit"], input[type="button"], input[type="reset"], [role="button"]'
            );
            for (const el of els) {
                const text = (
                    el.innerText || el.value || el.getAttribute('aria-label') || ''
                ).trim().substring(0, 200);
                if (!text || seen.has(text)) continue;
                seen.add(text);
                const type = el.type || el.tagName.toLowerCase();
                const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                results.push({text, type, disabled});
            }
            return results;
        }
        """
        try:
            buttons = await page.evaluate(js)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "url": page.url,
            "count": len(buttons),
            "buttons": buttons,
        }

    # -- Interaction --------------------------------------------------------

    @router.post(
        "/{session_id}/click_link",
        operation_id="browser_click_link",
        summary="Click a link by its visible text",
        description=(
            "Click the first link whose visible text matches the given string (case-insensitive). "
            "Use browser_get_links first to see available link texts."
        ),
    )
    async def click_link(
        session_id: str,
        text: str = Query(..., description="Text (or substring) of the link to click."),
    ):
        session = _get_session(session_id)
        page = session.page

        try:
            link = page.get_by_role("link", name=text)
            await link.first.click(timeout=30000)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not find or click link with text '{text}': {e}",
            )

        await page.wait_for_load_state("load")
        return {
            "status": "ok",
            "url": page.url,
            "title": await page.title(),
        }

    @router.post(
        "/{session_id}/click_button",
        operation_id="browser_click_button",
        summary="Click a button by its visible text",
        description=(
            "Click the first button whose visible text matches the given string (case-insensitive). "
            "Works for <button> elements and input[type=submit]."
        ),
    )
    async def click_button(
        session_id: str,
        text: str = Query(..., description="Text (or substring) of the button to click."),
    ):
        session = _get_session(session_id)
        page = session.page

        try:
            button = page.get_by_role("button", name=text)
            await button.first.click(timeout=30000)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Could not find or click button with text '{text}': {e}",
            )

        await page.wait_for_load_state("load")
        return {
            "status": "ok",
            "url": page.url,
            "title": await page.title(),
        }

    @router.post(
        "/{session_id}/fill_form",
        operation_id="browser_fill_form",
        summary="Fill form fields by label",
        description=(
            "Fill one or more form fields using their label, placeholder, or name as keys. "
            "Use browser_get_form_fields first to discover available fields. "
            "Set submit=true to press Enter after filling to submit the form."
        ),
    )
    async def fill_form(session_id: str, req: FillFormRequest):
        session = _get_session(session_id)
        page = session.page

        filled = []
        last_locator = None

        for label, value in req.fields.items():
            try:
                # Try label association first, then placeholder, then aria-label
                locator = page.get_by_label(label)
                count = await locator.count()
                if count == 0:
                    locator = page.get_by_placeholder(label)
                    count = await locator.count()
                if count == 0:
                    # Fall back to name attribute
                    locator = page.locator(f'[name="{label}"]')
                    count = await locator.count()
                if count == 0:
                    raise Exception(f"No field found matching '{label}'")

                target = locator.first
                tag = await target.evaluate("el => el.tagName")
                if tag == "SELECT":
                    await target.select_option(label=value, timeout=10000)
                else:
                    await target.fill(value, timeout=10000)
                last_locator = target
                filled.append(label)
            except Exception as e:
                return {
                    "status": "partial",
                    "filled": filled,
                    "error": f"Failed on field '{label}': {e}",
                }

        if req.submit and last_locator:
            await last_locator.press("Enter")
            await page.wait_for_load_state("load")

        return {
            "status": "ok",
            "filled": filled,
            "url": page.url,
            "title": await page.title(),
        }

    # -- Screenshot ---------------------------------------------------------

    @router.get(
        "/{session_id}/screenshot",
        operation_id="browser_screenshot",
        summary="Take a screenshot",
        description=(
            "Capture a screenshot of the current page and save it to a file. "
            "Returns the file path. Use display_file to show it to the user."
        ),
    )
    async def screenshot(
        session_id: str,
        full_page: bool = Query(False, description="Capture the full scrollable page."),
    ):
        session = _get_session(session_id)
        page = session.page

        try:
            screenshot_dir = os.path.join(tempfile.gettempdir(), "open-terminal-screenshots")
            os.makedirs(screenshot_dir, exist_ok=True)
            filename = f"screenshot_{session_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
            filepath = os.path.join(screenshot_dir, filename)
            await page.screenshot(type="png", full_page=full_page, path=filepath)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "url": page.url,
            "path": filepath,
            "format": "png",
        }

    # -- Escape hatch -------------------------------------------------------

    @router.post(
        "/{session_id}/evaluate",
        operation_id="browser_evaluate",
        summary="Evaluate JavaScript",
        description=(
            "Execute a JavaScript expression in the page and return the result. "
            "This is an escape hatch for advanced interactions not covered by other tools "
            "(e.g. scrolling, pressing keys, interacting with custom widgets)."
        ),
    )
    async def evaluate(session_id: str, req: EvaluateRequest):
        session = _get_session(session_id)
        page = session.page

        try:
            result = await page.evaluate(req.expression)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"result": result}

    return router
