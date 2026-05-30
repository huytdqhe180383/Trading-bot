"""
Quick account/balance check utility for the canonical CCXT gateway.
"""

from __future__ import annotations

import argparse

from data.live_feed import CCXTExchangeGateway


def main() -> None:
    parser = argparse.ArgumentParser(description="Check exchange balances and latest prices.")
    parser.add_argument("--exchange", default="okx", choices=["okx"])
    parser.add_argument("--mode", default="testnet", choices=["testnet", "live"])
    args = parser.parse_args()

    gateway = CCXTExchangeGateway(exchange_id=args.exchange, mode=args.mode)
    balances, prices = gateway.fetch_balances_and_prices()

    print(f"Exchange: {args.exchange} | mode: {args.mode}")
    print("Balances:")
    for asset in ["BTC", "ETH", "USDT"]:
        print(f"  {asset}: {balances.get(asset, 0.0):.8f}")
    print("Prices:")
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        print(f"  {symbol}: {prices.get(symbol, 0.0):.6f}")


if __name__ == "__main__":
    main()
