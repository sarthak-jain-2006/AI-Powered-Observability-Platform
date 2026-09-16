import time

from config import COLLECT_INTERVAL
from collectors.snapshot import take_snapshot
from utils.logger import get_logger

log = get_logger("collector")


def main():
    log.info(f"AI engine starting — collecting every {COLLECT_INTERVAL}s")

    # Fixed-rate loop rather than `schedule`: sampling regularity matters here.
    # A sequence model assumes evenly spaced steps, so the loop sleeps for
    # whatever is left of the interval and says so out loud when a round runs
    # long enough to push the next sample late.
    next_run = time.monotonic()
    while True:
        started = time.monotonic()
        try:
            take_snapshot()
        except Exception as e:
            log.error(f"Snapshot failed: {e}")

        elapsed = time.monotonic() - started
        if elapsed > COLLECT_INTERVAL:
            log.warning(
                f"Collection took {elapsed:.1f}s, longer than the {COLLECT_INTERVAL}s "
                f"interval — samples will be unevenly spaced"
            )

        next_run += COLLECT_INTERVAL
        sleep_for = next_run - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            # Fell behind; resync rather than trying to catch up in a burst.
            next_run = time.monotonic()


if __name__ == "__main__":
    main()
