"""
PDF 解析模块
用 pdfplumber 从财报 PDF 中提取文本
"""

from typing import List, Optional

import pdfplumber


def extract_text_from_pdf(pdf_file) -> str:
    """
    从上传的 PDF 文件中提取全部文本。

    参数:
        pdf_file: Streamlit 上传的文件对象（UploadedFile）
    返回:
        合并后的全文文本
    """
    texts: List[str] = []
    # pdfplumber 可直接读取文件流
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                texts.append(page_text)
    return "\n".join(texts)


def extract_tables_from_pdf(pdf_file) -> List[Optional[list]]:
    """
    从 PDF 中提取表格（后续可用来更精确地抓取财务数字）。

    参数:
        pdf_file: Streamlit 上传的文件对象
    返回:
        每页表格组成的列表
    """
    all_tables = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                all_tables.extend(tables)
    return all_tables
