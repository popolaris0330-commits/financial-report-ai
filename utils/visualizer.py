"""
财务数据可视化模块

使用 Plotly 生成核心指标卡片、盈利能力柱状图与财务比率雷达图。
配色：深蓝 + 灰色系；布局与字体针对中文显示优化。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# 主题配色
# ---------------------------------------------------------------------------
COLOR_PRIMARY = "#1a365d"       # 深蓝
COLOR_SECONDARY = "#2b6cb0"     # 中蓝
COLOR_ACCENT = "#4a5568"        # 深灰
COLOR_MUTED = "#718096"         # 中灰
COLOR_LIGHT = "#a0aec0"         # 浅灰
COLOR_BG = "#f7fafc"            # 背景灰
COLOR_GRID = "#e2e8f0"          # 网格线
COLOR_BAR = ["#1a365d", "#2c5282", "#2b6cb0", "#4a5568"]

FONT_FAMILY = (
    "Microsoft YaHei, SimHei, PingFang SC, "
    "Hiragino Sans GB, Noto Sans CJK SC, sans-serif"
)

# 指标别名：兼容 modules/metrics 与 utils/pdf_parser 两种字段名
METRIC_ALIASES: Dict[str, List[str]] = {
    "营业收入": ["营业收入", "营收", "营业总收入"],
    "净利润": ["净利润", "归母净利润"],
    "ROE": ["ROE", "净资产收益率"],
    "毛利率": ["毛利率", "销售毛利率"],
    "净利率": ["净利率", "净利润率", "销售净利率"],
    "资产负债率": ["资产负债率"],
}

CORE_CARD_METRICS = [
    ("营业收入", "营业收入", "amount"),
    ("净利润", "净利润", "amount"),
    ("ROE", "ROE", "ratio"),
    ("毛利率", "毛利率", "ratio"),
]

PROFITABILITY_METRICS = ["毛利率", "净利率", "ROE"]

RADAR_METRICS = ["ROE", "毛利率", "净利率", "资产负债率"]


def _get_metric(metrics: Dict[str, Any], canonical: str) -> Optional[float]:
    """按标准键名读取指标，自动尝试别名。"""
    for key in METRIC_ALIASES.get(canonical, [canonical]):
        val = metrics.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
    return None


def _format_amount(value: float) -> Tuple[str, str]:
    """
    将金额（元）格式化为 (显示数值, 单位后缀)。
    例：1.23 亿、456.78 万
    """
    abs_val = abs(value)
    if abs_val >= 1e8:
        return f"{value / 1e8:.2f}", " 亿元"
    if abs_val >= 1e4:
        return f"{value / 1e4:.2f}", " 万元"
    return f"{value:,.2f}", " 元"


def _format_ratio(value: float) -> Tuple[str, str]:
    """将比率格式化为 (显示数值, 单位后缀)。"""
    return f"{value:.2f}", " %"


def _base_layout(title: str, height: Optional[int] = None) -> Dict[str, Any]:
    """通用布局：中文友好字体、深蓝灰配色。"""
    layout: Dict[str, Any] = dict(
        title=dict(
            text=title,
            font=dict(size=18, color=COLOR_PRIMARY, family=FONT_FAMILY),
            x=0.02,
            xanchor="left",
        ),
        font=dict(family=FONT_FAMILY, color=COLOR_ACCENT, size=13),
        paper_bgcolor="white",
        plot_bgcolor=COLOR_BG,
        margin=dict(l=48, r=32, t=72, b=48),
    )
    if height is not None:
        layout["height"] = height
    return layout


def create_core_metric_cards(
    metrics: Dict[str, Any],
    title: str = "核心财务指标",
) -> go.Figure:
    """
    生成四格核心指标卡片：营业收入、净利润、ROE、毛利率。

    参数:
        metrics: 指标字典（金额单位：元；比率：百分数数值，如 15.2 表示 15.2%）
        title: 图表总标题

    返回:
        Plotly Figure，适合 st.plotly_chart 展示
    """
    fig = make_subplots(
        rows=1,
        cols=4,
        specs=[[{"type": "indicator"}] * 4],
        horizontal_spacing=0.06,
    )

    for col, (canonical, label, kind) in enumerate(CORE_CARD_METRICS, start=1):
        value = _get_metric(metrics, canonical)

        if value is None:
            fig.add_trace(
                go.Indicator(
                    mode="number",
                    value=0,
                    number=dict(
                        valueformat=" ",
                        font=dict(size=28, color=COLOR_LIGHT),
                    ),
                    title=dict(
                        text=f"{label}<br><span style='font-size:11px;color:{COLOR_MUTED}'>数据缺失</span>",
                        font=dict(size=14, color=COLOR_ACCENT),
                    ),
                ),
                row=1,
                col=col,
            )
            continue

        if kind == "amount":
            display, suffix = _format_amount(value)
            num_value = float(display.replace(",", ""))
            valueformat = (
                ",.2f" if "万" not in suffix and "亿" not in suffix else ".2f"
            )
        else:
            display, suffix = _format_ratio(value)
            num_value = float(display)
            valueformat = ".2f"

        fig.add_trace(
            go.Indicator(
                mode="number",
                value=num_value,
                number=dict(
                    valueformat=valueformat,
                    suffix=suffix,
                    font=dict(size=26, color=COLOR_PRIMARY),
                ),
                title=dict(
                    text=label,
                    font=dict(size=14, color=COLOR_ACCENT),
                ),
            ),
            row=1,
            col=col,
        )

    layout = _base_layout(title, height=220)
    layout.update(
        margin=dict(l=24, r=24, t=64, b=16),
    )
    fig.update_layout(**layout)
    return fig


def create_profitability_bar_chart(
    metrics: Dict[str, Any],
    title: str = "盈利能力分析",
) -> Optional[go.Figure]:
    """
    盈利能力柱状图：毛利率、净利率、ROE（有值的指标才绘制）。

    返回:
        Plotly Figure；若有效数据不足则返回 None
    """
    labels: List[str] = []
    values: List[float] = []

    for name in PROFITABILITY_METRICS:
        val = _get_metric(metrics, name)
        if val is not None:
            labels.append(name)
            values.append(val)

    if not labels:
        return None

    colors = [COLOR_BAR[i % len(COLOR_BAR)] for i in range(len(labels))]

    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                text=[f"{v:.2f}%" for v in values],
                textposition="outside",
                textfont=dict(family=FONT_FAMILY, color=COLOR_ACCENT, size=12),
                marker=dict(
                    color=colors,
                    line=dict(color=COLOR_PRIMARY, width=0.5),
                ),
                hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>",
            )
        ]
    )

    layout = _base_layout(title, height=400)
    layout.update(
        yaxis=dict(
            title=dict(text="比率 (%)", font=dict(color=COLOR_MUTED)),
            tickfont=dict(color=COLOR_ACCENT),
            gridcolor=COLOR_GRID,
            zerolinecolor=COLOR_LIGHT,
            range=[0, max(values) * 1.25 if values else 100],
        ),
        xaxis=dict(
            tickfont=dict(color=COLOR_ACCENT, size=13),
        ),
        showlegend=False,
    )
    fig.update_layout(**layout)
    return fig


def create_financial_radar_chart(
    metrics: Dict[str, Any],
    title: str = "财务比率雷达图",
) -> Optional[go.Figure]:
    """
    财务比率雷达图：ROE、毛利率、净利率、资产负债率（至少 2 项有值才绘制）。

    返回:
        Plotly Figure；若有效数据不足则返回 None
    """
    labels: List[str] = []
    values: List[float] = []

    for name in RADAR_METRICS:
        val = _get_metric(metrics, name)
        if val is not None:
            labels.append(name)
            values.append(val)

    if len(values) < 2:
        return None

    labels_closed = labels + [labels[0]]
    values_closed = values + [values[0]]

    fig = go.Figure(
        data=[
            go.Scatterpolar(
                r=values_closed,
                theta=labels_closed,
                fill="toself",
                fillcolor="rgba(43, 108, 176, 0.25)",
                line=dict(color=COLOR_SECONDARY, width=2),
                marker=dict(size=8, color=COLOR_PRIMARY),
                name="财务比率",
                hovertemplate="%{theta}<br>%{r:.2f}%<extra></extra>",
            )
        ]
    )

    layout = _base_layout(title, height=420)
    layout.update(
        polar=dict(
            bgcolor=COLOR_BG,
            radialaxis=dict(
                visible=True,
                gridcolor=COLOR_GRID,
                linecolor=COLOR_LIGHT,
                tickfont=dict(color=COLOR_MUTED, family=FONT_FAMILY),
                ticksuffix="%",
            ),
            angularaxis=dict(
                gridcolor=COLOR_GRID,
                linecolor=COLOR_LIGHT,
                tickfont=dict(color=COLOR_ACCENT, size=13, family=FONT_FAMILY),
            ),
        ),
        showlegend=False,
    )
    fig.update_layout(**layout)
    return fig


def create_all_charts(metrics: Dict[str, Any]) -> Dict[str, Optional[go.Figure]]:
    """
    一次性生成全部图表。

    返回:
        字典，键为图表名称，值为 Figure 或 None（数据不足时）
    """
    return {
        "core_cards": create_core_metric_cards(metrics),
        "profitability_bar": create_profitability_bar_chart(metrics),
        "financial_radar": create_financial_radar_chart(metrics),
    }


def test_visualize() -> None:
    """本地自测：用示例数据生成图表并保存为 HTML。"""
    sample = {
        "营业收入": 12_345_678_900.0,
        "净利润": 1_234_567_890.0,
        "ROE": 15.2,
        "毛利率": 42.5,
        "净利率": 10.1,
        "资产负债率": 48.0,
    }

    charts = create_all_charts(sample)
    for name, fig in charts.items():
        if fig is None:
            print(f"[{name}] 数据不足，跳过")
            continue
        out = f"test_{name}.html"
        fig.write_html(out, include_plotlyjs="cdn", config={"displayModeBar": False})
        print(f"[{name}] 已保存 -> {out}")


if __name__ == "__main__":
    test_visualize()
