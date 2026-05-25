# -*- coding: utf-8 -*-
import pandas as pd

df = pd.read_csv('data/stock_metrics.csv', encoding='utf-8-sig')
total = len(df)

def cov(col):
    if col not in df.columns:
        return '列不存在'
    n = int(df[col].notna().sum())
    numeric = pd.to_numeric(df[col], errors='coerce')
    nonzero = int((numeric > 0).sum())
    return f'{n}/{total} ({n/total:.0%})  非零={nonzero}'

print(f'总行数 : {total}')
print(f'量比   : {cov("量比")}')
print(f'振幅   : {cov("振幅")}')
print(f'换手率 : {cov("换手率")}')
print(f'市盈率 : {cov("市盈率-动态")}')
print(f'市净率 : {cov("市净率")}')
print(f'更新时间: {cov("更新时间")}')
print()
print('所有列名:', list(df.columns))
