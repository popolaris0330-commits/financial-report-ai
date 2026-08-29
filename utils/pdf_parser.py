"""
PDF 财报解析模块

从中文上市公司年报/半年报 PDF 中提取关键财务指标。
使用 pdfplumber 读文本，正则匹配常见指标同义词，金额统一换算为「元」。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber


# ---------------------------------------------------------------------------
# 指标定义：键为输出字段名；值按优先级排列（更具体的表述靠前）
# ---------------------------------------------------------------------------
METRIC_ALIASES: Dict[str, List[str]] = {
    "营业收入": [
        "营业总收入",
        "营业收入",
        "主营业务收入",
    ],
    "净利润": [
        "归属于上市公司股东的净利润",
        "归属于母公司所有者的净利润",
        "归属于母公司股东的净利润",
        "归母净利润",
        "净利润",
    ],
    "扣非净利润": [
        # 完整表述（同行）
        "归属于上市公司股东的扣除非经常性损益的净利润",
        "归属于母公司所有者的扣除非经常性损益的净利润",
        "扣除非经常性损益后的净利润",
        "扣除非经常性损益的净利润",
        # PDF 表格换行时常把数字夹在「扣除非经常性」与「损益的净利润」之间
        "归属于上市公司股东的扣除非经常性",
        "归属于母公司所有者的扣除非经常性",
        "扣非后净利润",
        "扣非净利润",
    ],
    "总资产": [
        "资产总计",
        "资产总额",
        "总资产",
    ],
    "净资产": [
        "归属于上市公司股东的净资产",
        "归属于母公司所有者权益合计",
        "归属于母公司股东的权益",
        "所有者权益合计",
        "股东权益合计",
        "净资产",
    ],
    "ROE": [
        "加权平均净资产收益率",
        "全面摊薄净资产收益率",
        "净资产收益率",
        "ROE",
    ],
    "毛利率": [
        "销售毛利率",
        "综合毛利率",
        "毛利率",
    ],
    "净利率": [
        "销售净利率",
        "净利润率",
        "净利率",
    ],
    "资产负债率": [
        "资产负债率",
        "负债合计/资产总计",
    ],
    "经营活动现金流": [
        "经营活动产生的现金流量净额",
        "经营活动现金流量净额",
        "经营活动产生的现金流量",
        "经营现金流净额",
        "经营活动现金流",
    ],
    "基本每股收益": [
        "基本每股收益",
        "每股收益（基本）",
        "每股收益",
    ],
}

# 比率类指标：值为百分数，不做「元」换算
RATIO_METRICS = {"ROE", "毛利率", "净利率", "资产负债率"}

# 金额单位 → 相对「元」的乘数
UNIT_TO_YUAN = {
    "亿元": 1e8,
    "亿": 1e8,
    "万元": 1e4,
    "万": 1e4,
    "千元": 1e3,
    "元": 1.0,
}

# 匹配带千分位的数字（可含负号、小数）
_NUM_RE = r"[+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[+-]?\d+(?:\.\d+)?"


def extract_text_from_pdf(
    pdf_path: str,
    max_pages: Optional[int] = None,
    start_page: int = 0,
) -> str:
    """
    用 pdfplumber 读取 PDF 文本并拼接。

    参数:
        pdf_path: PDF 文件路径
        max_pages: 最多读到第 N 页（1-based 上限）；None 表示读到末尾
        start_page: 从第几页开始（0-based）
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到 PDF 文件: {pdf_path}")

    texts: List[str] = []
    with pdfplumber.open(str(path)) as pdf:
        end = len(pdf.pages) if max_pages is None else min(max_pages, len(pdf.pages))
        for page in pdf.pages[start_page:end]:
            page_text = page.extract_text()
            if page_text:
                texts.append(page_text)
    return "\n".join(texts)


def _normalize_text(text: str) -> str:
    """折叠空白，便于跨行指标名匹配。"""
    text = text.replace("\u3000", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text


def _detect_default_unit(text: str) -> float:
    """
    从文中「单位：元/万元/亿元」推断默认金额单位乘数。
    找不到则默认按「元」处理。
    """
    # 优先匹配较靠前、且出现在主要会计数据附近的声明
    m = re.search(r"单位\s*[：:]\s*(亿元|万元|千元|元)", text)
    if m:
        return UNIT_TO_YUAN[m.group(1)]
    return 1.0


def _parse_number_token(raw: str) -> Optional[float]:
    """去掉千分位逗号并转为 float。"""
    try:
        return float(raw.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _unit_multiplier(unit: Optional[str], default: float = 1.0) -> float:
    if not unit:
        return default
    unit = unit.strip()
    if unit in UNIT_TO_YUAN:
        return UNIT_TO_YUAN[unit]
    # 「元/股」等按元计
    if unit.startswith("元"):
        return 1.0
    return default


def _build_alias_pattern(alias: str) -> str:
    """
    将别名转为允许字符间有空白的正则（应对 PDF 换行拆词）。
    例：扣除非经常性损益的净利润 → 扣\s*除\s*非\s*...
    """
    parts = [re.escape(ch) for ch in alias if not ch.isspace()]
    return r"\s*".join(parts)


def _find_metric_value(
    text: str,
    aliases: List[str],
    *,
    is_ratio: bool,
    default_unit_mul: float,
) -> Optional[float]:
    """
    在全文中按别名查找第一个合理数值。

    比率：期望带 % 或落在常见百分比区间附近。
    金额：解析后换算为元。
    """
    for alias in aliases:
        alias_pat = _build_alias_pattern(alias)

        if is_ratio:
            # 关键词后：可选括号 / 短连接语（提升至约、为 等），再跟数字与可选 %
            pattern = (
                rf"{alias_pat}"
                rf"(?:\s*[（(][^）)]*[）)])?"
                rf"(?:\s*(?:提升至|下降至|上升至|约为|达到|为|是|：|:))?"
                rf"\s*约?\s*"
                rf"({_NUM_RE})\s*(%)?"
            )
        else:
            # 关键词 + 可选（元/万元）+ 数字 + 可选单位
            pattern = (
                rf"{alias_pat}"
                rf"(?:\s*[（(]\s*(亿元|万元|千元|元(?:/股)?)\s*[）)])?"
                rf"\s*[：:]?\s*"
                rf"({_NUM_RE})"
                rf"(?:\s*(亿元|万元|万|亿|千元|元))?"
            )

        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            if is_ratio:
                # 跳过「同比…个百分点」类变动幅度
                window = text[m.start() : m.end() + 12]
                if "百分点" in window or "同比" in text[max(0, m.start() - 6) : m.start()]:
                    continue
                value = _parse_number_token(m.group(1))
                if value is None:
                    continue
                if abs(value) > 1000:
                    continue
                has_percent = m.group(2) is not None
                if has_percent:
                    return value
                if abs(value) <= 1:
                    return value * 100
                return value

            # 金额：group(1)=括号内单位, group(2)=数字, group(3)=后缀单位
            paren_unit = m.group(1)
            value = _parse_number_token(m.group(2))
            suffix_unit = m.group(3)
            if value is None:
                continue

            # 「净利润」勿误匹配「扣非净利润」上下文
            if alias == "净利润":
                start = max(0, m.start() - 30)
                ctx = text[start : m.start()]
                if re.search(r"扣\s*非|扣\s*除\s*非\s*经\s*常", ctx):
                    continue

            # 「净资产」勿匹配「净资产收益率」
            if alias in ("净资产", "股东权益合计", "所有者权益合计"):
                after = text[m.end() : m.end() + 12]
                if re.match(r"\s*收\s*益\s*率", after):
                    continue

            # 「每股收益」勿匹配「稀释每股收益」「扣非每股收益」前缀
            if alias == "每股收益":
                start = max(0, m.start() - 8)
                ctx = text[start : m.start()]
                if re.search(r"稀释|扣非|全面摊薄", ctx):
                    continue

            mul = _unit_multiplier(paren_unit or suffix_unit, default_unit_mul)
            return value * mul

    return None


# 常见于报告后部（如主要财务指标表）的指标；缺失时再补读后续页
_LATE_SECTION_METRICS = {"资产负债率"}


def parse_financial_report(
    pdf_path: str,
    *,
    max_pages: Optional[int] = None,
    prefer_pages: int = 50,
) -> Dict[str, Any]:
    """
    解析财报 PDF，返回关键财务指标字典。

    参数:
        pdf_path: PDF 文件路径
        max_pages: 最多读取页数；None 表示不设硬上限
        prefer_pages: 先扫前 N 页（主要会计数据通常在此）；
                      若后文常见指标仍缺失，再补读后续页面

    返回:
        字典，键为指标名；找不到则为 None。
        金额类单位为「元」；比率类为百分数数值（如 28.57 表示 28.57%）。
    """
    first_cap = prefer_pages if max_pages is None else min(prefer_pages, max_pages)
    raw = extract_text_from_pdf(pdf_path, max_pages=first_cap)
    text = _normalize_text(raw)
    default_unit = _detect_default_unit(text)

    result: Dict[str, Any] = {}
    for name, aliases in METRIC_ALIASES.items():
        is_ratio = name in RATIO_METRICS
        result[name] = _find_metric_value(
            text,
            aliases,
            is_ratio=is_ratio,
            default_unit_mul=default_unit,
        )

    missing_late = [
        k for k in _LATE_SECTION_METRICS if result.get(k) is None
    ]
    need_more = max_pages is None or (max_pages > first_cap)
    if missing_late and need_more:
        more = extract_text_from_pdf(
            pdf_path, max_pages=max_pages, start_page=first_cap
        )
        if more:
            text_all = text + " " + _normalize_text(more)
            default_unit = _detect_default_unit(text_all) or default_unit
            for name in missing_late:
                result[name] = _find_metric_value(
                    text_all,
                    METRIC_ALIASES[name],
                    is_ratio=name in RATIO_METRICS,
                    default_unit_mul=default_unit,
                )

    return result


def format_metrics(metrics: Dict[str, Any]) -> str:
    """将指标字典格式化为可读字符串（测试/调试用）。"""
    lines = []
    for k, v in metrics.items():
        if v is None:
            lines.append(f"  {k}: None")
        elif k in RATIO_METRICS:
            lines.append(f"  {k}: {v}%")
        elif k == "基本每股收益":
            lines.append(f"  {k}: {v} 元/股")
        else:
            lines.append(f"  {k}: {v:,.2f} 元")
    return "\n".join(lines)


def test_parse(pdf_path: str = "test_report.pdf") -> Dict[str, Any]:
    """
    直接运行测试：解析指定 PDF 并打印结果。

    用法:
        python -m utils.pdf_parser
        python utils/pdf_parser.py
        python utils/pdf_parser.py path/to/report.pdf
    """
    path = Path(pdf_path)
    if not path.is_file():
        # 兼容从任意 cwd 运行：相对项目根目录寻找
        alt = Path(__file__).resolve().parent.parent / pdf_path
        if alt.is_file():
            path = alt
        else:
            raise FileNotFoundError(f"测试 PDF 不存在: {pdf_path}")

    print(f"正在解析: {path}")
    metrics = parse_financial_report(str(path))
    print("提取结果:")
    print(format_metrics(metrics))
    found = sum(1 for v in metrics.values() if v is not None)
    print(f"\n共找到 {found}/{len(metrics)} 项指标")
    return metrics


if __name__ == "__main__":
    import sys

    pdf = sys.argv[1] if len(sys.argv) > 1 else "test_report.pdf"
    test_parse(pdf)
