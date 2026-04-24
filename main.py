import asyncio

from feeds import run_ws, poll_rest
from dashboard import render


async def main() -> None:
    await asyncio.gather(run_ws(), poll_rest(), render())


if __name__ == "__main__":
    asyncio.run(main())
