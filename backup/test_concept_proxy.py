# test_concept_proxy.py

import akshare as ak

df = ak.stock_board_concept_name_em()

print(df.columns.tolist())
print(df.head(20))

df.to_excel("output/test_concept_name_proxy.xlsx", index=False)