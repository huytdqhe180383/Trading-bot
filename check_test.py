from data.live_feed import get_client
client = get_client()
print('\n=== YOUR LIVE TESTNET BALANCES ===')
bals = client.account(recvWindow=60000)['balances']
for b in bals:
    if float(b['free']) > 0 or float(b['locked']) > 0:
        print(f"Asset: {b['asset']:<5} | Free: {b['free']:<12} | Locked: {b['locked']}")

print('\n=== LAST 3 BTCUSDT TRADES ===')
try:
    btc_trades = client.my_trades('BTCUSDT', recvWindow=60000)[-3:]
    for t in btc_trades:
        print(f"Price: {t['price']} | Qty: {t['qty']} | Realized Pnl: {t.get('realizedPnl', '0')}")
except Exception as e: print(e)

print('\n=== LAST 3 ETHUSDT TRADES ===')
try:
    eth_trades = client.my_trades('ETHUSDT', recvWindow=60000)[-3:]
    for t in eth_trades:
        print(f"Price: {t['price']} | Qty: {t['qty']} | Realized Pnl: {t.get('realizedPnl', '0')}")
except Exception as e: print(e)
