"""
财报 AI 解读器 - Streamlit 主程序

上传 PDF 财报 → 提取指标 → 可视化 → DeepSeek AI 分析
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from utils.ai_analyzer import _format_metric_value, generate_analysis
from utils.pdf_parser import RATIO_METRICS, parse_financial_report
from utils.visualizer import create_all_charts

# ---------------------------------------------------------------------------
# 页面与主题
# ---------------------------------------------------------------------------
PAGE_TITLE = "财报 AI 解读器"
PAGE_ICON = "📊"

COLOR_PRIMARY = "#1a365d"
COLOR_SECONDARY = "#2b6cb0"
COLOR_ACCENT = "#4a5568"
COLOR_MUTED = "#718096"
COLOR_BG = "#f7fafc"
COLOR_BORDER = "#e2e8f0"

METRIC_CATEGORIES = {
    "营业收入": "经营规模",
    "净利润": "盈利能力",
    "扣非净利润": "盈利能力",
    "总资产": "资产规模",
    "净资产": "资本结构",
    "ROE": "盈利能力",
    "毛利率": "盈利能力",
    "净利率": "盈利能力",
    "资产负债率": "偿债能力",
    "经营活动现金流": "现金流",
    "基本每股收益": "每股指标",
}


def _inject_styles() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: {COLOR_BG};
        }}
        .main-header {{
            background: linear-gradient(135deg, {COLOR_PRIMARY} 0%, {COLOR_SECONDARY} 100%);
            padding: 1.75rem 2rem;
            border-radius: 10px;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 14px rgba(26, 54, 93, 0.18);
        }}
        .main-header h1 {{
            color: #ffffff !important;
            font-size: 1.85rem !important;
            font-weight: 700 !important;
            margin: 0 0 0.35rem 0 !important;
            letter-spacing: 0.02em;
        }}
        .main-header p {{
            color: rgba(255, 255, 255, 0.88) !important;
            margin: 0 !important;
            font-size: 0.95rem;
        }}
        .section-card {{
            background: #ffffff;
            border: 1px solid {COLOR_BORDER};
            border-left: 4px solid {COLOR_SECONDARY};
            border-radius: 8px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 1.25rem;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
        }}
        .section-title {{
            color: {COLOR_PRIMARY};
            font-size: 1.15rem;
            font-weight: 600;
            margin: 0 0 0.75rem 0;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid {COLOR_BORDER};
        }}
        div[data-testid="stSidebar"] {{
            background-color: #ffffff;
            border-right: 1px solid {COLOR_BORDER};
        }}
        div[data-testid="stSidebar"] .stMarkdown h2 {{
            color: {COLOR_PRIMARY};
            font-size: 1.05rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.markdown(
        f"""
        <div class="main-header">
            <h1>{PAGE_ICON} {PAGE_TITLE}</h1>
            <p>上传上市公司 PDF 财报，自动提取关键指标、生成专业图表，并由 DeepSeek 撰写分析摘要</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section(title: str) -> None:
    st.markdown(
        f'<div class="section-card"><p class="section-title">{title}</p>',
        unsafe_allow_html=True,
    )


def _close_section() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# API Key 与元数据
# ---------------------------------------------------------------------------
def _configure_api_key() -> None:
    """侧边栏：可选 API Key，统一写入 DEEPSEEK_API_KEY 环境变量。"""
    load_dotenv()

    st.sidebar.header("系统配置")

    env_key = os.getenv("DEEPSEEK_API_KEY", "") or ""
    masked = f"{env_key[:6]}…{env_key[-4:]}" if len(env_key) > 12 else ("已配置" if env_key else "未配置")

    st.sidebar.caption(f"当前环境变量：{masked}")

    sidebar_key = st.sidebar.text_input(
        "DeepSeek API Key（可选）",
        type="password",
        placeholder="sk-…",
        help="留空则使用 .env 或系统环境变量中的 DEEPSEEK_API_KEY",
    )

    if sidebar_key and sidebar_key.strip():
        os.environ["DEEPSEEK_API_KEY"] = sidebar_key.strip()

    st.sidebar.divider()
    st.sidebar.markdown("**报告信息**（用于 AI 分析，可修改）")


def _guess_metadata(filename: str) -> Tuple[str, str]:
    """从文件名粗略推断公司名称与报告期。"""
    stem = Path(filename).stem

    period = "未知报告期"
    if m := re.search(r"(\d{4})年(?:度)?(?:半年度|中期|半年报)", stem):
        period = f"{m.group(1)}年半年度报告"
    elif m := re.search(r"(\d{4})年(?:度)?(?:年报|年度报告)", stem):
        period = f"{m.group(1)}年年度报告"
    elif m := re.search(r"(\d{4})中期", stem):
        period = f"{m.group(1)}年中期报告"
    elif m := re.search(r"(\d{4})Q([1-4])", stem, re.IGNORECASE):
        period = f"{m.group(1)}年第{m.group(2)}季度报告"
    elif m := re.search(r"(\d{4})", stem):
        period = f"{m.group(1)}年报告"

    company = re.sub(r"\d{4}.*", "", stem)
    company = re.sub(r"[_\-\s]+", "", company)
    company = company or "未知公司"
    return company, period


def _init_session_state() -> None:
    defaults = {
        "metrics": None,
        "file_name": None,
        "company_name": "",
        "report_period": "",
        "analysis": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ---------------------------------------------------------------------------
# 数据处理与展示
# ---------------------------------------------------------------------------
def _parse_uploaded_pdf(uploaded_file) -> Dict[str, Any]:
    suffix = Path(uploaded_file.name).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        return parse_financial_report(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _build_metrics_dataframe(metrics: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name, value in metrics.items():
        rows.append(
            {
                "指标名称": name,
                "类别": METRIC_CATEGORIES.get(name, "其他"),
                "数值": _format_metric_value(name, value),
                "状态": "已提取" if value is not None else "数据缺失",
            }
        )
    return pd.DataFrame(rows)


def _render_metrics_table(metrics: Dict[str, Any]) -> None:
    _section("关键财务指标")
    df = _build_metrics_dataframe(metrics)
    found = sum(1 for v in metrics.values() if v is not None)
    total = len(metrics)
    st.caption(f"共提取 {found}/{total} 项指标 · 金额单位：元 · 比率单位：%")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "指标名称": st.column_config.TextColumn("指标名称", width="medium"),
            "类别": st.column_config.TextColumn("类别", width="small"),
            "数值": st.column_config.TextColumn("数值", width="medium"),
            "状态": st.column_config.TextColumn("状态", width="small"),
        },
    )
    _close_section()


def _render_charts(metrics: Dict[str, Any]) -> None:
    _section("财务可视化")
    charts = create_all_charts(metrics)

    core = charts.get("core_cards")
    if core is not None:
        st.plotly_chart(core, use_container_width=True, config={"displayModeBar": False})

    col1, col2 = st.columns(2)
    with col1:
        bar = charts.get("profitability_bar")
        if bar is not None:
            st.plotly_chart(bar, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("盈利能力指标不足，暂无法绘制柱状图。")

    with col2:
        radar = charts.get("financial_radar")
        if radar is not None:
            st.plotly_chart(radar, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("财务比率数据不足，暂无法绘制雷达图（至少需要 2 项）。")

    _close_section()


def _render_ai_section(metrics: Dict[str, Any]) -> None:
    _section("AI 智能分析")

    company = st.session_state.company_name.strip() or "未知公司"
    period = st.session_state.report_period.strip() or "未知报告期"
    st.caption(f"分析对象：{company} · {period}")

    if st.button("生成 AI 分析", type="primary", use_container_width=False):
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            st.error("请先在侧边栏填写 API Key，或在 .env 中配置 DEEPSEEK_API_KEY。")
        else:
            with st.spinner("DeepSeek 正在撰写分析摘要，请稍候…"):
                result = generate_analysis(metrics, company, period)
            st.session_state.analysis = result

    if st.session_state.analysis:
        st.markdown(st.session_state.analysis)

    _close_section()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _inject_styles()
    _init_session_state()
    _configure_api_key()
    _render_header()

    uploaded = st.file_uploader(
        "上传 PDF 财报",
        type=["pdf"],
        help="支持 A 股上市公司年报、半年报等 PDF 格式定期报告",
    )

    if uploaded is not None:
        if uploaded.name != st.session_state.file_name:
            with st.spinner("正在解析 PDF，提取财务指标…"):
                try:
                    metrics = _parse_uploaded_pdf(uploaded)
                except Exception as exc:
                    st.error(f"解析失败：{exc}")
                    return

                company, period = _guess_metadata(uploaded.name)
                st.session_state.metrics = metrics
                st.session_state.file_name = uploaded.name
                st.session_state.company_name = company
                st.session_state.report_period = period
                st.session_state.analysis = None

            st.success(f"已解析：{uploaded.name}")

    if st.session_state.metrics is not None:
        st.session_state.company_name = st.sidebar.text_input(
            "公司名称",
            value=st.session_state.company_name,
        )
        st.session_state.report_period = st.sidebar.text_input(
            "报告期",
            value=st.session_state.report_period,
            placeholder="如：2024年年度报告",
        )

        _render_metrics_table(st.session_state.metrics)
        _render_charts(st.session_state.metrics)
        _render_ai_section(st.session_state.metrics)
    else:
        st.info("请在上方上传 PDF 财报文件，系统将自动提取指标并生成图表。")

        with st.expander("使用说明", expanded=False):
            st.markdown(
                """
                1. **上传**：选择本地 PDF 财报（建议为文字版而非纯扫描件）。
                2. **指标表**：自动提取营收、净利润、ROE、毛利率等 11 项核心指标。
                3. **图表**：展示核心指标卡片、盈利能力柱状图与财务比率雷达图。
                4. **AI 分析**：配置 `DEEPSEEK_API_KEY` 后点击按钮，生成专业中文分析摘要。
                """
            )


if __name__ == "__main__":
    main()
