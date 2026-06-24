# -*- coding: utf-8 -*-
"""
Streamlit 可视化入口：
1. 用 ml_match.py 按模板股寻找相似度前 N 只股票；
2. 自动取前 5 只作为模板池，运行 ml_grid_test_modified.py；
3. 汇总 grid test 结果，寻找最新生成的 pkl；
4. 提供每日调用 pkl 的命令面板。

放置位置建议：项目根目录 stock_selection/ml_web_app.py
运行：streamlit run ml_web_app.py
"""

from __future__ import annotations

import os
import re
import sys
import time
import glob
import shlex
import subprocess
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st


# =========================
# 基础工具
# =========================

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIRS = [
    PROJECT_ROOT / "output",
    PROJECT_ROOT / "output" / "ml_match",
    PROJECT_ROOT / "output" / "ml_grid",
    PROJECT_ROOT / "output" / "models",
    PROJECT_ROOT / "models",
]

CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_command(cmd: list[str] | str, cwd: Path | None = None) -> tuple[int, str]:
    """运行命令并返回 returncode + 合并日志。

    cmd 可以是 list，也可以是字符串。Windows 下字符串会用 shell=True，
    这样能更好兼容中文路径、空格路径和带引号的 pkl 路径。
    """
    cwd = cwd or PROJECT_ROOT
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    use_shell = isinstance(cmd, str)

    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        shell=use_shell,
    )

    lines: list[str] = []
    log_box = st.empty()

    while True:
        line = process.stdout.readline() if process.stdout else ""
        if line:
            lines.append(line)
            # 只展示最后 200 行，避免页面卡顿。
            log_box.code("".join(lines[-200:]), language="text")
        elif process.poll() is not None:
            break
        else:
            time.sleep(0.05)

    return process.returncode or 0, "".join(lines)


def list_recent_files(patterns: list[str], start_ts: float | None = None) -> list[Path]:
    files: list[Path] = []
    for base in OUTPUT_DIRS:
        if not base.exists():
            continue
        for pattern in patterns:
            files.extend(Path(p) for p in glob.glob(str(base / pattern)))
            files.extend(Path(p) for p in glob.glob(str(base / "**" / pattern), recursive=True))

    unique_files = []
    seen = set()
    for f in files:
        if not f.exists() or f in seen:
            continue
        if start_ts is not None and f.stat().st_mtime < start_ts:
            continue
        seen.add(f)
        unique_files.append(f)

    unique_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return unique_files


def read_table_file(path: Path) -> pd.DataFrame:
    try:
        if path.suffix.lower() in {".xlsx", ".xls"}:
            return pd.read_excel(path, dtype={"代码": str, "code": str, "ts_code": str})
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path, dtype={"代码": str, "code": str, "ts_code": str})
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()


def normalize_code(value) -> str:
    text = str(value or "").strip()
    m = CODE_PATTERN.search(text)
    return m.group(1) if m else ""


def extract_codes_from_df(df: pd.DataFrame, top_n: int = 5) -> list[str]:
    if df is None or df.empty:
        return []

    data = df.copy()

    # 尽量按相似度排序。
    sim_candidates = [
        "相似度", "similarity", "score", "cosine_similarity", "余弦相似度", "综合相似度"
    ]
    for col in sim_candidates:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
            data = data.sort_values(col, ascending=False)
            break

    code_cols = ["代码", "code", "ts_code", "股票代码", "证券代码"]
    found: list[str] = []
    for col in code_cols:
        if col not in data.columns:
            continue
        for value in data[col].tolist():
            code = normalize_code(value)
            if code and code not in found:
                found.append(code)
            if len(found) >= top_n:
                return found

    # 兜底：从所有列文本中抓 6 位代码。
    for _, row in data.iterrows():
        text = " ".join(str(x) for x in row.tolist())
        for code in CODE_PATTERN.findall(text):
            if code not in found:
                found.append(code)
            if len(found) >= top_n:
                return found

    return found[:top_n]


def find_match_result(start_ts: float, top_n: int = 5) -> tuple[pd.DataFrame, list[str], Path | None]:
    files = list_recent_files(["*.xlsx", "*.csv"], start_ts=start_ts)
    keywords = ["match", "similar", "相似", "ml"]
    files = [f for f in files if any(k.lower() in f.name.lower() for k in keywords)] + files

    for f in files:
        df = read_table_file(f)
        codes = extract_codes_from_df(df, top_n=top_n)
        if codes:
            return df, codes, f

    return pd.DataFrame(), [], None


def extract_codes_from_log(log: str, top_n: int = 5, exclude: str = "") -> list[str]:
    found: list[str] = []
    for code in CODE_PATTERN.findall(log or ""):
        if code == exclude:
            continue
        if code not in found:
            found.append(code)
        if len(found) >= top_n:
            break
    return found


def find_grid_result(start_ts: float) -> tuple[pd.DataFrame, Path | None]:
    files = list_recent_files(["*.xlsx", "*.csv"], start_ts=start_ts)
    keywords = ["grid", "test", "backtest", "ml"]
    files = [f for f in files if any(k.lower() in f.name.lower() for k in keywords)] + files

    for f in files:
        df = read_table_file(f)
        if df is not None and not df.empty:
            return df, f

    return pd.DataFrame(), None


def sort_grid_by_win_rate(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    data = df.copy()
    win_cols = [
        "胜率", "win_rate", "WinRate", "成功率", "正收益比例", "profit_win_rate"
    ]
    score_cols = [
        "平均收益", "avg_return", "mean_return", "收益率", "总收益", "score", "综合得分"
    ]

    sort_cols = []
    ascending = []
    for col in win_cols:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
            sort_cols.append(col)
            ascending.append(False)
            break
    for col in score_cols:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
            sort_cols.append(col)
            ascending.append(False)
            break

    if sort_cols:
        data = data.sort_values(sort_cols, ascending=ascending)
    return data


def find_recent_pkl(start_ts: float | None = None) -> list[Path]:
    return list_recent_files(["*.pkl", "*.joblib"], start_ts=start_ts)


def list_project_model_files(project_root: Path) -> list[Path]:
    """扫描当前工程内所有 pkl/joblib，第三步可任意选择。"""
    patterns = ["**/*.pkl", "**/*.joblib"]
    files: list[Path] = []

    exclude_parts = {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".idea",
        ".vscode",
    }

    for pattern in patterns:
        for f in project_root.glob(pattern):
            if not f.is_file():
                continue
            if any(part in exclude_parts for part in f.parts):
                continue
            files.append(f)

    unique_files = []
    seen = set()
    for f in files:
        resolved = f.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_files.append(resolved)

    unique_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return unique_files


def comma_clean(text: str) -> str:
    return ",".join([x.strip() for x in str(text).replace("，", ",").split(",") if x.strip()])


# =========================
# 页面
# =========================

st.set_page_config(page_title="量化 ML 相似匹配训练台", layout="wide")
st.title("量化 ML 相似匹配训练台")
st.caption("流程：模板股相似匹配 → 自动取前5只 → Grid Test → 生成/选择 pkl → 每日调用模型。")

with st.sidebar:
    st.header("运行环境")
    project_root_text = st.text_input("项目根目录", value=str(PROJECT_ROOT))
    PROJECT_ROOT = Path(project_root_text).resolve()
    st.write("当前时间：", now_text())
    st.write("Python：", sys.executable)

st.subheader("一、模板股相似匹配")

col1, col2, col3 = st.columns(3)
with col1:
    template_code = st.text_input("模板股票代码", value="002636")
    date_start = st.text_input("模板开始日期", value="2025-10-23")
    date_end = st.text_input("模板结束日期", value="2026-06-03")
with col2:
    match_threshold = st.number_input("相似度阈值", value=0.70, min_value=0.0, max_value=1.0, step=0.01)
    top_k = st.number_input("匹配输出 top-k", value=20, min_value=1, max_value=200, step=1)
    recent_windows = st.number_input("最近匹配窗口数", value=1, min_value=1, max_value=50, step=1)
with col3:
    auto_pick_n = st.number_input("自动取前 N 只跑 Grid", value=5, min_value=1, max_value=20, step=1)
    workers = st.number_input("并发 workers", value=8, min_value=1, max_value=32, step=1)
    skip_backtest = st.checkbox("match 阶段跳过回测", value=True)

match_cmd = [
    sys.executable,
    "cli/ml_match.py",
    "--code", template_code.strip(),
    "--date-start", date_start.strip(),
    "--date-end", date_end.strip(),
    "--threshold", str(match_threshold),
    "--top-k", str(int(top_k)),
    "--recent-windows", str(int(recent_windows)),
    "--workers", str(int(workers)),
]
if skip_backtest:
    match_cmd.append("--skip-backtest")

st.code(" ".join(shlex.quote(x) for x in match_cmd), language="bash")

if "matched_codes" not in st.session_state:
    st.session_state["matched_codes"] = ""
if "best_pkl" not in st.session_state:
    st.session_state["best_pkl"] = ""

if st.button("1. 运行相似匹配", type="primary"):
    start_ts = time.time()
    ret, log = run_command(match_cmd, cwd=PROJECT_ROOT)
    st.write("返回码：", ret)

    df_match, codes, match_file = find_match_result(start_ts, top_n=int(auto_pick_n))
    if not codes:
        codes = extract_codes_from_log(log, top_n=int(auto_pick_n), exclude=template_code.strip())

    if codes:
        st.session_state["matched_codes"] = ",".join(codes)
        st.success(f"已提取前 {len(codes)} 只相似股票：{','.join(codes)}")
    else:
        st.warning("没有自动提取到相似股票代码。请查看日志，手动填入下面的 Grid 股票代码。")

    if match_file:
        st.info(f"匹配结果文件：{match_file}")
    if df_match is not None and not df_match.empty:
        st.dataframe(df_match.head(int(top_k)), use_container_width=True)

st.subheader("二、用相似票跑 Grid Test")

col4, col5, col6 = st.columns(3)
with col4:
    grid_codes = st.text_input(
        "Grid 股票代码，默认取上一步前 N 只",
        value=st.session_state.get("matched_codes", "") or "603678,603303,002484,003036,603773",
    )
    grid_mode = st.selectbox("Grid 模式", options=["combination_range", "single", "all"], index=0)
    grid_threshold = st.number_input("Grid 阈值", value=0.65, min_value=0.0, max_value=1.0, step=0.01)
with col5:
    horizons = st.text_input("horizons", value="15,20,30")
    targets = st.text_input("targets", value="20,30,40")
    hold_days = st.text_input("hold-days", value="10,15,20")
with col6:
    grid_workers = st.number_input("Grid workers", value=8, min_value=1, max_value=32, step=1)

clean_grid_codes = comma_clean(grid_codes)
grid_cmd = [
    sys.executable,
    "cli/ml_grid_test_modified.py",
    "--codes", clean_grid_codes,
    "--mode", grid_mode,
    "--threshold", str(grid_threshold),
    "--horizons", comma_clean(horizons),
    "--targets", comma_clean(targets),
    "--hold-days", comma_clean(hold_days),
    "--workers", str(int(grid_workers)),
]

st.code(" ".join(shlex.quote(x) for x in grid_cmd), language="bash")

if st.button("2. 运行 Grid Test 并查找 pkl", type="primary"):
    if not clean_grid_codes:
        st.error("请先填入 Grid 股票代码。")
    else:
        start_ts = time.time()
        ret, log = run_command(grid_cmd, cwd=PROJECT_ROOT)
        st.write("返回码：", ret)

        df_grid, grid_file = find_grid_result(start_ts)
        if grid_file:
            st.info(f"Grid 结果文件：{grid_file}")
        if df_grid is not None and not df_grid.empty:
            sorted_grid = sort_grid_by_win_rate(df_grid)
            st.write("按胜率/收益排序后的前 20 行：")
            st.dataframe(sorted_grid.head(20), use_container_width=True)
        else:
            st.warning("没有自动找到 Grid 结果表。")

        pkls = find_recent_pkl(start_ts)
        if pkls:
            best_pkl = pkls[0]
            st.session_state["best_pkl"] = str(best_pkl)
            st.success(f"发现最新模型文件：{best_pkl}")
            st.write("最近生成的模型：")
            st.dataframe(pd.DataFrame({"模型文件": [str(p) for p in pkls[:20]]}), use_container_width=True)
        else:
            st.warning("没有发现新生成的 .pkl/.joblib。请确认 ml_grid_test_modified.py 是否已经支持保存模型文件。")

st.subheader("三、每日调用 pkl 扫描")

st.caption("这里会扫描当前工程目录下所有 .pkl/.joblib；也可以手动粘贴任意模型路径。")

model_files = list_project_model_files(PROJECT_ROOT)
model_options = [str(p) for p in model_files]

# 刚刚 Grid Test 生成的模型放最前面，但不限制只能选它。
if st.session_state.get("best_pkl") and st.session_state["best_pkl"] not in model_options:
    model_options.insert(0, st.session_state["best_pkl"])

col_model1, col_model2 = st.columns([2, 1])
with col_model1:
    selected_pkl = st.selectbox(
        "从当前工程中选择模型 pkl/joblib",
        options=model_options if model_options else [""],
        index=0,
        help="按修改时间倒序排列。不是固定最新模型，你可以选工程里的任意 pkl/joblib。",
    )
with col_model2:
    st.metric("工程内模型数量", len(model_options))

manual_pkl = st.text_input(
    "或者手动输入模型路径，可覆盖上面的选择",
    value="",
    placeholder=r"例如：D:\Vscode\股票\stock_selection\output\ml_models\xxx.pkl",
)

final_pkl = manual_pkl.strip().strip('"').strip("'") if manual_pkl.strip() else selected_pkl

if final_pkl:
    final_pkl_path = Path(final_pkl)
    if not final_pkl_path.is_absolute():
        final_pkl_path = PROJECT_ROOT / final_pkl_path

    if final_pkl_path.exists():
        mtime = datetime.fromtimestamp(final_pkl_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        st.success(f"当前选择模型：{final_pkl_path}")
        st.caption(f"修改时间：{mtime}")
    else:
        st.warning(f"当前模型路径不存在：{final_pkl_path}")

st.caption("下面这个命令模板按你的项目实际预测脚本改一次即可。可用变量：{pkl}、{workers}、{top_k}")
default_predict_template = "python cli/ml_predict.py --model {pkl} --top-k {top_k} --workers {workers}"
predict_template = st.text_input("每日扫描命令模板", value=default_predict_template)
predict_top_k = st.number_input("每日输出 top-k", value=50, min_value=1, max_value=500, step=1)
predict_workers = st.number_input("每日扫描 workers", value=8, min_value=1, max_value=32, step=1, key="predict_workers")

if final_pkl:
    daily_cmd_text = predict_template.format(
        pkl=f'"{str(final_pkl_path)}"',
        workers=int(predict_workers),
        top_k=int(predict_top_k),
    )
else:
    daily_cmd_text = ""

st.code(daily_cmd_text, language="bash")

if st.button("3. 调用选中的 pkl 每日扫描", type="primary"):
    if not final_pkl:
        st.error("没有选择或输入 pkl/joblib 文件。")
    elif not Path(final_pkl_path).exists():
        st.error(f"模型文件不存在：{final_pkl_path}")
    elif not daily_cmd_text.strip():
        st.error("每日扫描命令为空。")
    else:
        # 用 shell=True 处理 Windows 路径空格/中文路径更稳。
        ret, log = run_command(daily_cmd_text if os.name == "nt" else shlex.split(daily_cmd_text), cwd=PROJECT_ROOT)
        st.write("返回码：", ret)

st.divider()
st.markdown(
    """
### 使用建议

1. 第一次先运行“相似匹配”，确认自动提取的前 5 只是否符合你的图形审美。
2. 再运行 Grid Test。若没有生成 pkl，说明当前 `ml_grid_test_modified.py` 还没有保存模型逻辑，需要在那个脚本里补 `joblib.dump()` 或 `pickle.dump()`。
3. 每日扫描命令模板只需要配置一次，后面直接选 pkl 点击运行。
"""
)
