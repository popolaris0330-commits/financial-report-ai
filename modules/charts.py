"""
图表可视化模块
用 Plotly 绘制营收趋势、利润构成、财务比率雷达图
"""

from typing import List, Dict, Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def build_metrics_dataframe(metrics_list: List[Dict[str, Any]]) -> pd.DataFrame:
    """把多份报告的指标列表转成 DataFrame，方便画图和对比。"""
    return pd.DataFrame(metrics_list)


def chart_revenue_trend(df: pd.DataFrame):
    """
    营收趋势图（柱状图 / 折线均可）。
    需要列：报告名称、营收
    """
    if df.empty or "营收" not in df.columns:
        return None

    plot_df = df.dropna(subset=["营收"])
    if plot_df.empty:
        return None

    fig = px.bar(
        plot_df,
        x="报告名称",
        y="营收",
        title="营收趋势",
        labels={"营收": "营收（提取值）", "报告名称": "报告"},
    )
    fig.update_layout(template="plotly_white")
    return fig


def chart_profit_composition(metrics: Dict[str, Any]):
    """
    利润构成饼图（单份报告）。
    简化示意：用净利润与「营收 - 净利润」近似展示结构。
    后续可扩展为毛利、营业利润、净利润等更细拆分。
    """
    revenue = metrics.get("营收")
    net_profit = metrics.get("净利润")

    if revenue is None or net_profit is None or revenue <= 0:
        return None

    # 粗略拆分：净利润 + 其余成本费用
    other = max(revenue - net_profit, 0)
    fig = go.Figure(
        data=[
            go.Pie(
                labels=["净利润", "成本与费用等"],
                values=[net_profit, other],
                hole=0.35,
            )
        ]
    )
    fig.update_layout(title="利润构成（示意）", template="plotly_white")
    return fig


def chart_ratio_radar(metrics: Dict[str, Any]):
    """
    财务比率雷达图。
    使用 ROE、毛利率、资产负债率（有值才画）。
    """
    ratio_names = ["ROE", "毛利率", "资产负债率"]
    values = []
    labels = []

    for name in ratio_names:
        val = metrics.get(name)
        if val is not None:
            labels.append(name)
            values.append(val)

    if len(values) < 2:
        return None

    # 雷达图需要首尾闭合
    labels_closed = labels + [labels[0]]
    values_closed = values + [values[0]]

    fig = go.Figure(
        data=[
            go.Scatterpolar(
                r=values_closed,
                theta=labels_closed,
                fill="toself",
                name="财务比率",
            )
        ]
    )
    fig.update_layout(
        title="财务比率雷达图",
        polar=dict(radialaxis=dict(visible=True)),
        template="plotly_white",
        showlegend=False,
    )
    return fig
