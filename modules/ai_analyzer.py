"""
AI 分析模块
通过 OpenAI 兼容接口调用 DeepSeek，生成财报摘要与风险提示
"""

import os
from typing import Dict, Any, Optional

from openai import OpenAI


def _get_client() -> Optional[OpenAI]:
    """
    创建 DeepSeek 客户端。
    优先读环境变量，也可用 Streamlit secrets（在 app 里注入到环境变量）。
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    return OpenAI(api_key=api_key, base_url=base_url)


def generate_analysis(metrics: Dict[str, Any], report_text_excerpt: str = "") -> str:
    """
    根据提取的财务指标，生成 AI 分析摘要和风险提示。

    参数:
        metrics: 指标字典
        report_text_excerpt: 财报原文摘录（可选，控制长度以免超 token）
    返回:
        模型生成的中文分析文本；若未配置 API Key，返回提示信息
    """
    client = _get_client()
    if client is None:
        return (
            "未配置 DEEPSEEK_API_KEY。\n"
            "请在 .env 或 .streamlit/secrets.toml 中设置后再生成 AI 分析。"
        )

    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    excerpt = (report_text_excerpt or "")[:3000]

    prompt = f"""你是一名专业的财务分析师。请根据以下财务指标和财报摘录，用简洁中文输出：
1. 核心经营情况摘要（3～5 句话）
2. 主要亮点
3. 风险提示（至少 2 条）

财务指标：
{metrics}

财报摘录：
{excerpt}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是严谨、客观的财务分析助手，避免夸大结论。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content or "模型未返回内容。"
