import asyncio
import random
from asyncio import AbstractEventLoop
from contextlib import asynccontextmanager
import psutil
from typing import Callable, Optional, TypeVar

from selenium_async._selenium import Firefox, FirefoxOptions, Service, WebDriver
from selenium_async.options import BrowserType, Options
from selenium_async.pool import Pool, default_pool

T = TypeVar("T")


async def run_sync(
    func: Callable[[WebDriver], T],
    *,
    browser: BrowserType = "firefox",
    headless: bool = True,
    executable_path: str,
    binary_location: str,
    loop: Optional[AbstractEventLoop] = None,
    pool: Optional[Pool] = None,
) -> T:
    if loop is None:
        loop = asyncio.get_event_loop()
    if pool is None:
        pool = default_pool()

    options = Options(
        browser=browser,
        headless=headless,
        executable_path=executable_path,
        binary_location=binary_location,
    )

    async with use_browser(options=options, pool=pool) as driver:
        return await asyncio.to_thread(func, driver)


@asynccontextmanager
async def use_browser(
    options: Optional[Options] = None,
    *,
    pool: Optional[Pool] = None,
):
    if pool is None:
        pool = default_pool()
    if options is None:
        options = Options()

    await pool.semaphore.acquire()
    try:
        if options in pool.resources:
            driver = pool.resources[options].pop()
            if len(pool.resources[options]) == 0:
                del pool.resources[options]
        else:
            # close webdrivers if there are too many in the pool that
            # don't match our desired options
            too_many = len(pool) - (pool.max_size - 1)
            if too_many > 0:
                weighted_keys = [
                    k for k, v in pool.resources.items() for _ in range(len(v))
                ]
                random.shuffle(weighted_keys)
                remove_keys = weighted_keys[0:too_many]
                drivers: list[WebDriver] = []
                for key in remove_keys:
                    drivers.append(pool.resources[key].pop())
                    if len(pool.resources[key]) == 0:
                        del pool.resources[key]

                def _close_drivers():
                    for driver in drivers:
                        driver.quit()

                await asyncio.to_thread(_close_drivers)

            # create new driver
            driver = await launch(options)

        try:
            yield driver
        except:
            # if error, don't return driver back to pool
            try:
                driver.quit()
            except:
                pass
            raise
    finally:
        pid = driver.service.process.pid
        driver.quit()
        driver.close()
        psutil.Process(pid).terminate()
        pool.semaphore.release()


async def launch(options: Optional[Options] = None) -> WebDriver:
    return await asyncio.to_thread(lambda: launch_sync(options))


def launch_sync(options: Optional[Options] = None) -> WebDriver:
    if options is None:
        options = Options()
    if options.browser == "firefox":
        firefox_options = FirefoxOptions()
        if options.headless:
            firefox_options.add_argument("--headless")

        firefox_options.binary_location = options.binary_location

        return Firefox(
            options=firefox_options,
            service=Service(executable_path=options.executable_path),
        )
    if options.browser == "chrome":
        raise NotImplementedError(f"@TODO Implement browser {repr(options.browser)}")

    raise NotImplementedError(f"Not sure how to open browser {repr(options.browser)}")
