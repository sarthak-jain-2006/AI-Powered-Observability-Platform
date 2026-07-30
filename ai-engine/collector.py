import time
import schedule
from config import COLLECT_INTERVAL
from collectors.snapshot import take_snapshot
from utils.logger import get_logger

log = get_logger("collector")

def main():
    log.info(f"AI engine starting — collecting every {COLLECT_INTERVAL}s")

    # Take one immediately so we don't wait 30s for the first
    take_snapshot()

    schedule.every(COLLECT_INTERVAL).seconds.do(take_snapshot)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()