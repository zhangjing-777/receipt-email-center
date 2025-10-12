import re
import logging
from playwright.async_api import async_playwright


logger = logging.getLogger(__name__)


def extract_gmail_forwarding_links(email_body: str) -> dict:
    links = {
        "confirm": re.search(r'https://[\w.-]*google\.com/mail/vf-[^"\s<>]+', email_body).group(0)
                   if re.search(r'https://[\w.-]*google\.com/mail/vf-[^"\s<>]+', email_body) else None,
        "cancel": re.search(r'https://[\w.-]*google\.com/mail/uf-[^"\s<>]+', email_body).group(0)
                  if re.search(r'https://[\w.-]*google\.com/mail/uf-[^"\s<>]+', email_body) else None
    }
    logger.info(f"Extracted links: {links}")
    return links


async def confirm_gmail_forwarding_link(link: str):
    logger.info(f"Start confirming Gmail forwarding link: {link}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        logger.info(f"🔗 Opening link: {link}")
        await page.goto(link, wait_until="networkidle")

        # Wait for the confirm button, up to 5 seconds
        try:
            # The confirm button may be <a> or <input>, use multiple selectors as fallback
            await page.wait_for_selector('text="Confirm"', timeout=5000)
            await page.click('text="Confirm"')
            logger.info("✅ Successfully clicked confirm button")
        except Exception as e:
            logger.warning(f"⚠️ Could not find 'Confirm' button, it may have already been confirmed or the link is invalid: {e}")

        await page.wait_for_timeout(3000)  # Wait a few seconds for redirect
        await browser.close()
    logger.info(f"Finished confirming Gmail forwarding link: {link}")