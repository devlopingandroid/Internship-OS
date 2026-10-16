import asyncio
import json
import sys
import threading
import socket
import ipaddress
from urllib.parse import urlsplit
from .normalization import valid_url
from pathlib import Path
from playwright.async_api import async_playwright

async def public_destination(url):
    if not valid_url(url): return False
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, urlsplit(url).hostname, None)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (OSError, ValueError): return False


PROFILE = Path(__file__).resolve().parents[1] / "profile.json"


async def _autofill_worker(url: str, ready_evt: threading.Event, result_holder: dict, job_dict: dict = None):
    try:
        p = json.loads(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else {}
        name = p.get("full_name", "")
        parts = name.split()
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        cover_text = ""
        if job_dict and job_dict.get("cover_letter"):
            cover_text = job_dict["cover_letter"]
        elif p.get("cover_letter"):
            cover_text = p.get("cover_letter")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            page = await browser.new_page()
            async def guard(route):
                if route.request.is_navigation_request() and not await public_destination(route.request.url):
                    await route.abort()
                else: await route.continue_()
            await page.route('**/*', guard)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                if not await public_destination(page.url): raise ValueError('Application redirected to a non-public destination')
                await page.wait_for_timeout(1500)
            except Exception as e:
                result_holder["error"] = f"Failed to load page: {e}"
                ready_evt.set()
                try:
                    await page.wait_for_event("close", timeout=3600000)
                except Exception:
                    pass
                await browser.close()
                return

            fields = [
                (["first name", "firstname", "given name"], first_name),
                (["last name", "lastname", "surname", "family name"], last_name),
                (["full name", "your name", "candidate name", "name"], name),
                (["email", "e-mail"], p.get("email", "")),
                (["phone", "mobile", "telephone", "contact"], p.get("phone", "")),
                (["linkedin"], p.get("linkedin_url", "")),
                (["github"], p.get("github_url", "")),
                (["portfolio", "personal website", "website"], p.get("portfolio_url", "")),
                (["cover letter", "cover_letter", "note", "message", "why do you want", "additional information"], cover_text),
            ]

            filled = []
            loc = page.locator("input:not([type=hidden]):not([type=password]), textarea")
            try:
                count = await loc.count()
                for terms, value in fields:
                    if not value or value.startswith("YOUR ") or value == "you@example.com":
                        continue
                    for i in range(min(count, 80)):
                        item = loc.nth(i)
                        try:
                            if not await item.is_visible() or not await item.is_enabled():
                                continue
                            attrs = " ".join(
                                filter(
                                    None,
                                    [
                                        await item.get_attribute("name"),
                                        await item.get_attribute("id"),
                                        await item.get_attribute("placeholder"),
                                        await item.get_attribute("aria-label"),
                                        await item.get_attribute("autocomplete"),
                                    ],
                                )
                            ).lower()
                            if await item.input_value():
                                continue
                            if any(t in attrs for t in terms):
                                await item.fill(value)
                                filled.append(terms[0])
                                break
                        except Exception:
                            pass
            except Exception:
                pass

            result_holder["data"] = {
                "url": url,
                "filled_fields": filled,
                "message": f"Autofilled {len(filled)} fields ({', '.join(filled) if filled else 'none matched'}). Inspect the browser window and submit manually.",
            }
            ready_evt.set()

            # Wait for user to close the browser. Never click Submit or Apply.
            try:
                await page.wait_for_event("close", timeout=3600000)
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
    except Exception as e:
        result_holder["error"] = str(e)
        ready_evt.set()


def _thread_runner(url: str, ready_evt: threading.Event, result_holder: dict, job_dict: dict = None):
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_autofill_worker(url, ready_evt, result_holder, job_dict))
    finally:
        try:
            loop.close()
        except Exception:
            pass


async def prepare_application(url: str, job_dict: dict = None):
    if not await public_destination(url): raise ValueError('Application URL must resolve to a public destination')
    ready_evt = threading.Event()
    result_holder = {}

    thread = threading.Thread(
        target=_thread_runner,
        args=(url, ready_evt, result_holder, job_dict),
        daemon=True,
    )
    thread.start()

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, ready_evt.wait, 50.0)

    if "error" in result_holder:
        raise RuntimeError(result_holder["error"])
    if "data" in result_holder:
        return result_holder["data"]

    return {
        "url": url,
        "filled_fields": [],
        "message": "Browser launched. Review the window and submit manually.",
    }
