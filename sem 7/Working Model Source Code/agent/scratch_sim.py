import json, os, glob

reports = glob.glob('data/eval_report_*.json')
latest = sorted(reports)[-1]
with open(latest) as f:
    data = json.load(f)

capital = 1000000.0
results = data['results']
results.sort(key=lambda x: x['as_of'])

print('DATE       | TICKER         | ACTION | FWD RET | PROFIT/LOSS | BALANCE')
print('-'*75)

for r in results:
    profit = capital * r['pnl']
    capital += profit
    if r['action'] != 'hold':
        print(f"{r['as_of']} | {r['instrument']:14} | {r['action'].upper():6} | {r['fwd_ret']:>7.2%} | INR {profit:>10,.2f} | INR {capital:,.2f}")
    else:
        pass

print('-'*75)
print(f'Total Return : {((capital - 1000000)/1000000):.2%}')
print(f'Final Capital: INR {capital:,.2f}')
