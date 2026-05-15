from __future__ import annotations

from data_fetcher import refresh_market_cache


def main() -> None:
    summary, messages = refresh_market_cache()
    for message in messages:
        print(message)
    print(f"缓存股票数量：{summary['count']}")
    print(f"最近更新时间：{summary['latest_update']}")


if __name__ == "__main__":
    main()
