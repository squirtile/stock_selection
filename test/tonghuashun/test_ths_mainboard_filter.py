# -*- coding: utf-8 -*-

from iFinDPy import *
from datetime import datetime
import pandas as pd


USERNAME = "sjjksy081"
PASSWORD = "NFS6anh7"


def ths_login():
    ret = THS_iFinDLogin(USERNAME, PASSWORD)
    print("登录返回码:", ret)

    if ret in {0, -201}:
        print("同花顺 iFinD 登录成功")
    else:
        raise RuntimeError(f"同花顺 iFinD 登录失败，返回码：{ret}")


def ths_logout():
    THS_iFinDLogout()
    print("同花顺 iFinD 已退出")


def is_main_board(code: str) -> bool:
    """
    判断是否为 A股主板股票。
    code 示例：
    600000.SH
    000001.SZ
    688270.SH
    """

    if not isinstance(code, str):
        return False

    symbol = code.split(".")[0]

    # 沪市主板
    if symbol.startswith(("600", "601", "603", "605")):
        return True

    # 深市主板，包含中小板老代码 002
    if symbol.startswith(("000", "001", "002", "003")):
        return True

    return False


def get_all_a_stock_codes():
    """
    获取全部 A 股股票代码。
    使用同花顺专题报表接口 THS_DR。
    """

    today_str = datetime.today().strftime("%Y%m%d")
    print("查询日期:", today_str)

    data_alla = THS_DR(
        "p03291",
        f"date={today_str};blockname=001005010;iv_type=allcontract",
        "p03291_f001:Y,p03291_f002:Y,p03291_f003:Y,p03291_f004:Y"
    )

    if data_alla.errorcode != 0:
        raise RuntimeError(f"获取全部A股失败: {data_alla.errmsg}")

    df = data_alla.data

    if df is None or df.empty:
        raise RuntimeError("全部A股列表为空")

    # p03291_f002 通常是证券代码
    codes = df["p03291_f002"].dropna().astype(str).tolist()

    print(f"全部A股数量: {len(codes)}")

    return codes


def fetch_realtime_quotes(codes, batch_size=300):
    """
    批量获取实时行情。
    指标：
    - thscode / security_name：代码和名称，部分账号字段名可能不同
    - latest：最新价
    - total_mv：总市值，注意不同接口可能单位不同
    """

    result_list = []

    indicators = "latest;total_mv;security_name"

    for i in range(0, len(codes), batch_size):
        batch_codes = codes[i:i + batch_size]
        code_str = ",".join(batch_codes)

        print(f"正在获取实时行情: {i + 1}-{min(i + batch_size, len(codes))}/{len(codes)}")

        rq = THS_RQ(code_str, indicators)

        if rq.errorcode != 0:
            print(f"当前批次获取失败: {rq.errmsg}")
            continue

        if rq.data is not None and not rq.data.empty:
            result_list.append(rq.data)

    if not result_list:
        return pd.DataFrame()

    return pd.concat(result_list, ignore_index=True)


def normalize_market_value(df: pd.DataFrame) -> pd.DataFrame:
    """
    把总市值统一转换成亿元。
    注意：
    不同 iFinD 字段返回单位可能不一样。
    如果 total_mv 返回的是元，则除以 1e8。
    如果已经是亿元，则不用除。
    这里做一个简单兼容判断。
    """

    if "total_mv" not in df.columns:
        raise RuntimeError(f"返回数据中没有 total_mv 字段，实际字段为：{df.columns.tolist()}")

    df["total_mv"] = pd.to_numeric(df["total_mv"], errors="coerce")

    max_mv = df["total_mv"].max()

    # 如果最大市值特别大，大概率单位是“元”
    if pd.notna(max_mv) and max_mv > 10000000:
        df["总市值_亿元"] = df["total_mv"] / 100000000
    else:
        df["总市值_亿元"] = df["total_mv"]

    return df


def filter_mainboard_price_mv(df: pd.DataFrame) -> pd.DataFrame:
    """
    筛选：
    1. 主板
    2. 最新价 < 200
    3. 总市值 200-1000 亿
    """

    # 找代码列
    code_col = None
    for col in ["thscode", "THSCODE", "代码", "code", "seccode"]:
        if col in df.columns:
            code_col = col
            break

    if code_col is None:
        # 有些 THS_RQ 返回的代码列可能叫 time 或者没有明显字段
        print("当前返回字段:", df.columns.tolist())
        raise RuntimeError("没有找到股票代码字段，请根据实际返回字段调整 code_col")

    # 股票名称字段兼容
    name_col = None
    for col in ["security_name", "ths_stock_short_name_stock", "name", "股票简称", "简称"]:
        if col in df.columns:
            name_col = col
            break

    df["代码"] = df[code_col].astype(str)
    df["最新价"] = pd.to_numeric(df["latest"], errors="coerce")

    if name_col:
        df["名称"] = df[name_col].astype(str)
    else:
        df["名称"] = ""

    df = normalize_market_value(df)

    filtered = df[
        df["代码"].apply(is_main_board)
        & (df["最新价"] < 200)
        & (df["总市值_亿元"] >= 200)
        & (df["总市值_亿元"] <= 1000)
    ].copy()

    filtered = filtered.sort_values("总市值_亿元", ascending=True)

    return filtered[["代码", "名称", "最新价", "总市值_亿元"]]


def main():
    pd.options.display.width = 320
    pd.options.display.max_columns = None

    ths_login()

    try:
        codes = get_all_a_stock_codes()

        # 先只保留主板代码，减少实时行情请求量
        mainboard_codes = [code for code in codes if is_main_board(code)]
        print(f"主板股票数量: {len(mainboard_codes)}")

        realtime_df = fetch_realtime_quotes(mainboard_codes, batch_size=300)

        if realtime_df.empty:
            print("没有获取到实时行情数据")
            return

        print("实时行情返回字段:")
        print(realtime_df.columns.tolist())

        result = filter_mainboard_price_mv(realtime_df)

        print("\n筛选结果:")
        print(result)

        today_str = datetime.today().strftime("%Y%m%d")
        output_file = f"ths_mainboard_price_mv_{today_str}.csv"
        result.to_csv(output_file, index=False, encoding="utf-8-sig")

        print(f"\n已保存到: {output_file}")
        print(f"命中数量: {len(result)}")

    finally:
        ths_logout()


if __name__ == "__main__":
    main()