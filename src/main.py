"""Main entry point for the Apify Actor."""

from __future__ import annotations

from apify import Actor

from .scraper_core import run_scraper


class _ActorLogAdapter:
    """Adapt Actor.log to scraper_core log interface (debug/info/warning/exception)."""

    def debug(self, msg: str, exc_info: bool = False) -> None:
        Actor.log.debug(msg)

    def info(self, msg: str) -> None:
        Actor.log.info(msg)

    def warning(self, msg: str) -> None:
        Actor.log.warning(msg)

    def exception(self, msg: str) -> None:
        Actor.log.exception(msg)


async def main() -> None:
    """Entry point of the Amazon Search & Product Scraper Actor."""
    async with Actor:
        raw_input = await Actor.get_input() or {}

        log = _ActorLogAdapter()
        await run_scraper(
            raw_input,
            launch_browser_kwargs={"headless": Actor.configuration.headless, "args": ["--disable-gpu"]},
            proxy=None,
            log=log,
            push_data=Actor.push_data,
        )
