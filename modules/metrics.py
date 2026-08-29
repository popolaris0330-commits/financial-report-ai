"""
财务指标提取模块
从财报文本中识别关键指标（营收、净利润、ROE 等）
当前为占位实现，后续用正则 / 表格解析完善
"""

from typing import Any, Dict
import re


# 常见指标的中文别名，方便在文本中匹配
METRIC_ALIASES = {
    "营收": ["营业收入", "营业总收入", "主营业务收入", "营收"],
    "净利润": ["净利润", "归属于母公司所有者的净利润", "归母净利润"],
    "ROE": ["净资产收益率", "加权平均净资产收益率", "ROE"],
    "毛利率": ["毛利率", "销售毛利率"],
    "资产负债率": ["资产负债率", "负债合计/资产总计"],
}


def _find_number_near_keyword(text: str, keywords: list) -> Any:
    """
    在关键词附近查找数字（简化版）。
    匹配形如「营业收入 1,234.56」或「净利润：12.3亿元」的模式。
    找不到则返回 None。
    """
    for kw in keywords:
        # 关键词后跟可选单位说明，再跟数字
        pattern = rf"{re.escape(kw)}[：:\s]*([+-]?\d[\d,]*(?:\.\d+)?)\s*(?:亿|万|%)?"
        match = re.search(pattern, text)
        if match:
            raw = match.group(1).replace(",", "")
            try:
                return float(raw)
            except ValueError:
                continue
    return None


def extract_metrics(text: str, report_name: str = "未命名") -> Dict[str, Any]:
    """
    从财报文本中提取关键财务指标。

    参数:
        text: PDF 提取出的全文
        report_name: 报告名称（如文件名），用于多份对比
    返回:
        指标字典，例如 {"报告名称": "...", "营收": 100.5, ...}
    """
    result: Dict[str, Any] = {"报告名称": report_name}

    for metric_name, aliases in METRIC_ALIASES.items():
        value = _find_number_near_keyword(text, aliases)
        result[metric_name] = value

    return result
