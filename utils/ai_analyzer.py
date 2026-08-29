"""
AI 财报分析模块

基于 pdf_parser 提取的财务指标，调用 DeepSeek（OpenAI 兼容接口）
生成专业的中文财报分析摘要。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from openai import APIConnectionError, APIError, AuthenticationError, OpenAI, RateLimitError

# 与 pdf_parser 保持一致：比率类为百分数，金额类单位为「元」
RATIO_METRICS = {"ROE", "毛利率", "净利率", "资产负债率"}

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是一名资深证券分析师，擅长解读 A 股上市公司定期报告。
写作要求：
1. 语气客观、专业、克制，避免营销式夸大或绝对化表述。
2. 每个判断必须引用具体数字；没有数据支撑的结论不要写。
3. 指标缺失时明确写「数据缺失」，严禁编造、估算或补全任何数字。
4. 金额可换算为「亿元/万元」便于阅读，但须与给定数据一致。
5. 比率类指标按百分数理解（如 15.2 表示 15.2%）。
6. 输出使用简体中文 Markdown，按指定小节标题组织，不要添加未要求的章节。"""


def _get_client(api_key: Optional[str] = None) -> OpenAI:
    """从环境变量或传入参数创建 DeepSeek 客户端。
    
    参数:
        api_key: 用户传入的 API Key，优先使用
    """
    # 优先使用传入的 Key
    key = api_key or os.getenv("DEEPSEEK_API_KEY")
    
    if not key or not key.strip():
        raise ValueError(
            "未检测到 API Key。请在侧边栏输入您的 DeepSeek API Key，"
            "或在 .env 中配置 DEEPSEEK_API_KEY。"
        )

    base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"

    return OpenAI(api_key=key.strip(), base_url=base_url)


def _format_metric_value(name: str, value: Any) -> str:
    """将单项指标格式化为可读字符串；缺失则为「数据缺失」。"""
    if value is None:
        return "数据缺失"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "数据缺失"

    if name in RATIO_METRICS:
        return f"{num:.2f}%"
    if name == "基本每股收益":
        return f"{num:.4f} 元/股"
    # 金额：元 → 按量级展示
    abs_num = abs(num)
    if abs_num >= 1e8:
        return f"{num / 1e8:.2f} 亿元"
    if abs_num >= 1e4:
        return f"{num / 1e4:.2f} 万元"
    return f"{num:,.2f} 元"


def format_metrics_for_prompt(metrics: Dict[str, Any]) -> str:
    """将指标字典整理为 Prompt 中的条目列表。"""
    if not metrics:
        return "（无可用指标，全部视为数据缺失）"

    lines = []
    for name, value in metrics.items():
        lines.append(f"- {name}：{_format_metric_value(name, value)}")
    return "\n".join(lines)


def _build_user_prompt(
    metrics: Dict[str, Any],
    company_name: str,
    report_period: str,
) -> str:
    metrics_block = format_metrics_for_prompt(metrics)
    return f"""请基于下列已提取财务数据，对「{company_name}」{report_period}财务报告撰写分析摘要。

【公司名称】{company_name}
【报告期】{report_period}

【财务指标】
{metrics_block}

请严格按以下五个小节输出（使用二级 Markdown 标题）：

## 核心财务概览
概述规模类指标（营收、净利润、总资产、净资产、经营现金流、每股收益等），引用具体数字；缺失项标注「数据缺失」。

## 盈利能力分析
围绕毛利率、净利率、ROE、扣非净利润等讨论盈利质量与水平；无数据则写「数据缺失」，勿推测。

## 偿债能力分析
围绕资产负债率及可推断的杠杆与偿债压力展开；相关指标缺失时明确说明。

## 风险提示
至少给出 2 条风险点，每条须绑定具体数字或「数据缺失」这一事实本身（例如关键指标缺失导致无法充分评估）。

## 关注建议
给出 2～4 条后续跟踪建议（如需关注的指标、同比/环比、现金流与扣非差异等），保持审慎，不构成投资建议。

注意：全文不要编造未提供的数字或同比/环比变动；若无法判断趋势，直接说明依据不足。"""


def generate_analysis(
    metrics: Dict[str, Any],
    company_name: str,
    report_period: str,
    *,
    api_key: Optional[str] = None,  # ← 新增参数
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> str:
    """
    调用 DeepSeek 生成财报分析摘要。

    参数:
        metrics: pdf_parser.parse_financial_report 返回的指标字典
        company_name: 公司名称（如「贵州茅台」）
        report_period: 报告期（如「2024年年度报告」「2025年半年度报告」）
        api_key: 用户传入的 DeepSeek API Key，优先使用
        temperature: 采样温度，越低越稳定
        max_tokens: 最大生成 token 数

    返回:
        AI 生成的分析文本（Markdown）
    """
    company_name = (company_name or "").strip() or "未知公司"
    report_period = (report_period or "").strip() or "未知报告期"
    metrics = metrics or {}

    try:
        # 把用户的 Key 传给 _get_client
        client = _get_client(api_key=api_key)
    except ValueError as e:
        return str(e)

    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
    user_prompt = _build_user_prompt(metrics, company_name, report_period)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except AuthenticationError:
        return "DeepSeek API 鉴权失败：请检查您的 API Key 是否正确、是否仍有效。"
    except RateLimitError:
        return "DeepSeek API 触发限流，请稍后重试。"
    except APIConnectionError:
        return "无法连接 DeepSeek API，请检查网络或 DEEPSEEK_BASE_URL 配置。"
    except APIError as e:
        return f"DeepSeek API 调用失败：{e}"
    except Exception as e:
        return f"生成分析时发生未预期错误：{type(e).__name__}: {e}"

    content: Optional[str] = None
    try:
        content = response.choices[0].message.content
    except (IndexError, AttributeError):
        return "模型未返回有效内容。"

    text = (content or "").strip()
    return text if text else "模型未返回有效内容。"


def test_analyze(
    metrics: Optional[Dict[str, Any]] = None,
    company_name: str = "示例股份",
    report_period: str = "2024年年度报告",
) -> str:
    """
    简单自测入口。

    用法:
        python -m utils.ai_analyzer
        python utils/ai_analyzer.py
    """
    from dotenv import load_dotenv

    load_dotenv()

    if metrics is None:
        metrics = {
            "营业收入": 1_234_567_890.0,
            "净利润": 123_456_789.0,
            "扣非净利润": None,
            "总资产": 5_000_000_000.0,
            "净资产": 2_500_000_000.0,
            "ROE": 15.2,
            "毛利率": 42.5,
            "净利率": 10.1,
            "资产负债率": 48.0,
            "经营活动现金流": 98_000_000.0,
            "基本每股收益": 1.25,
        }

    print(f"公司: {company_name} | 报告期: {report_period}")
    print("指标预览:")
    print(format_metrics_for_prompt(metrics))
    print("\n正在调用 DeepSeek…\n")
    result = generate_analysis(metrics, company_name, report_period)
    print(result)
    return result


if __name__ == "__main__":
    test_analyze()
