import asyncio

from dashboard import render
from feeds import poll_rest, run_ws, state
from persistence import run_persistence


async def main() -> None:
    await asyncio.gather(run_ws(), poll_rest(), render(), run_persistence(state))


if __name__ == "__main__":
    asyncio.run(main())
