import redis
from rq import Worker

from config import settings


def main() -> None:
    connection = redis.from_url(settings.redis_url)
    Worker(["market-scans"], connection=connection).work()


if __name__ == "__main__":
    main()
