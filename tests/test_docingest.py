"""文档解析测试（Phase 6 切片一）。

fixture 全部现造，不往仓库里塞二进制文件：xlsx 用 openpyxl 写、csv 用标准库、
PDF 手写一份最小的合法字节。重点覆盖**坏输入**——用户会传空文件、损坏文件、
扫描件 PDF、以及本阶段还不支持的图片，每一种都必须给出能看懂的说明而不是异常。
"""
from __future__ import annotations

import json

from studio_backend.docingest import SAMPLE_ROWS, as_tool_output, ingest


def _xlsx(path, sheets):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return path


def _make_pdf(text: bytes = b"Hello PDF") -> bytes:
    """现造一份最小的合法 PDF。

    手写字节而不是用生成库：pypdf 只读不写文本，装 reportlab 只为一个 fixture
    不值得。但 xref 表和 %%EOF 必须齐全——少了 pypdf 直接报 "EOF marker not
    found" 拒绝解析（第一版就是这么挂的）。
    """
    stream = b"BT /F1 12 Tf 20 100 Td (" + text + b") Tj ET"
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(index).encode() + b" 0 obj" + body + b"endobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer<</Size " + str(len(objects) + 1).encode() + b"/Root 1 0 R>>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    )
    return bytes(out)


# ── xlsx ─────────────────────────────────────────────────


def test_xlsx_reports_sheets_columns_and_sample(tmp_path):
    path = _xlsx(
        tmp_path / "orders.xlsx",
        {"订单": [["order_id", "status", "amount"], ["A1", "shipped", 100],
                  ["A2", "pending", 250]]},
    )
    r = ingest(path)
    assert r["kind"] == "xlsx"
    sheet = r["detail"]["sheets"][0]
    assert sheet["name"] == "订单"
    assert sheet["columns"] == ["order_id", "status", "amount"]
    assert sheet["sample_rows"][0] == ["A1", "shipped", 100]
    assert "order_id" in r["summary"]


def test_xlsx_sample_is_truncated(tmp_path):
    """整张表塞进模型上下文既贵又没用——摘要只给前几行。"""
    rows = [["c"]] + [[i] for i in range(100)]
    path = _xlsx(tmp_path / "big.xlsx", {"S": rows})
    sheet = ingest(path)["detail"]["sheets"][0]
    assert len(sheet["sample_rows"]) == SAMPLE_ROWS
    assert sheet["row_count"] == 101  # 行数照报，只是不给全部数据


def test_xlsx_with_multiple_sheets(tmp_path):
    path = _xlsx(
        tmp_path / "multi.xlsx",
        {"A": [["x"], [1]], "B": [["y"], [2]]},
    )
    r = ingest(path)
    assert [s["name"] for s in r["detail"]["sheets"]] == ["A", "B"]


def test_xlsx_result_is_json_serialisable(tmp_path):
    """openpyxl 会吐出 datetime 之类的非 JSON 类型，摘要要能落盘。"""
    import datetime

    path = _xlsx(
        tmp_path / "dates.xlsx",
        {"S": [["when"], [datetime.datetime(2026, 1, 1, 12, 0)]]},
    )
    json.dumps(ingest(path), ensure_ascii=False)  # 不抛就算过


# ── csv ──────────────────────────────────────────────────


def test_csv_reports_columns_and_row_count(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    r = ingest(path)
    assert r["kind"] == "csv"
    assert r["detail"]["columns"] == ["a", "b"]
    assert r["detail"]["row_count"] == 2


def test_csv_sniffs_semicolon_delimiter(tmp_path):
    """分号分隔在中文 Excel 导出里很常见。写死逗号会把整行读成一列。"""
    path = tmp_path / "semi.csv"
    path.write_text("a;b;c\n1;2;3\n4;5;6\n", encoding="utf-8")
    assert ingest(path)["detail"]["columns"] == ["a", "b", "c"]


def test_empty_csv_is_an_error_not_a_crash(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("   \n", encoding="utf-8")
    assert ingest(path)["kind"] == "error"


# ── pdf ──────────────────────────────────────────────────


def test_pdf_extracts_text(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(_make_pdf())
    r = ingest(path)
    assert r["kind"] == "pdf"
    assert r["detail"]["page_count"] == 1
    assert "Hello PDF" in r["detail"]["pages"][0]


def test_pdf_without_a_text_layer_says_so(tmp_path):
    """扫描件只有图片没有文本层。要说清楚是扫描件，别让用户以为解析器坏了。"""
    path = tmp_path / "scan.pdf"
    path.write_bytes(_make_pdf(b""))  # 有页面但没有文字
    r = ingest(path)
    assert r["kind"] == "pdf"
    assert "扫描件" in r["summary"]


def test_corrupt_pdf_is_an_error_not_a_crash(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
    assert ingest(path)["kind"] == "error"


# ── text / structured ────────────────────────────────────


def test_markdown_is_read_as_text(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# 标题\n正文内容", encoding="utf-8")
    r = ingest(path)
    assert r["kind"] == "text"
    assert "正文内容" in r["detail"]["text"]


def test_json_structure_is_described(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text('{"a": 1, "b": [1,2,3]}', encoding="utf-8")
    r = ingest(path)
    assert r["kind"] == "json"
    assert r["detail"]["data"]["b"] == [1, 2, 3]
    assert "a" in r["summary"]


def test_yaml_structure_is_described(tmp_path):
    path = tmp_path / "cfg.yaml"
    path.write_text("stages:\n  - name: a\n", encoding="utf-8")
    r = ingest(path)
    assert r["kind"] == "yaml"
    assert r["detail"]["data"]["stages"][0]["name"] == "a"


def test_malformed_json_is_an_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    r = ingest(path)
    assert r["kind"] == "error"
    assert "JSON" in r["summary"]


# ── 不支持 / 边界 ────────────────────────────────────────


def test_image_says_it_is_not_supported_yet_and_why(tmp_path):
    """本阶段不做图片。要说清是"还没做"而不是"读不了这个文件"。"""
    path = tmp_path / "flow.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    r = ingest(path)
    assert r["kind"] == "error"
    assert "多模态" in r["summary"]


def test_unknown_extension_lists_what_is_supported(tmp_path):
    path = tmp_path / "thing.docx"
    path.write_bytes(b"PK\x03\x04" + b"0" * 40)
    r = ingest(path)
    assert r["kind"] == "error"
    assert ".xlsx" in r["summary"] and ".csv" in r["summary"]


def test_empty_file_is_an_error(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    assert ingest(path)["kind"] == "error"


def test_missing_file_is_an_error(tmp_path):
    assert ingest(tmp_path / "nope.csv")["kind"] == "error"


def test_xlsx_suffix_on_a_non_xlsx_file_is_an_error(tmp_path):
    """用户把后缀改错是常事——不能让解析器把异常抛到上传接口去。"""
    path = tmp_path / "fake.xlsx"
    path.write_text("这其实是纯文本", encoding="utf-8")
    assert ingest(path)["kind"] == "error"


# ── 给元 agent 的输出 ────────────────────────────────────


def test_tool_output_marks_content_as_data_not_instructions(tmp_path):
    """第一次有外部文件内容进入元 agent 上下文。文件里可以写着像指令的话，
    输出必须把边界和"这是数据"讲清楚。"""
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    out = as_tool_output("t.csv", ingest(path))
    assert "数据" in out and "不是指令" in out
    assert "t.csv" in out


def test_tool_output_for_an_error_starts_with_Error(tmp_path):
    out = as_tool_output("x.png", ingest(tmp_path / "x.png"))
    assert out.startswith("Error:")


def test_tool_output_truncates_huge_detail(tmp_path):
    """绕过摘要截断把整份文件读进上下文的路要堵上。"""
    # 用 .txt 而不是 .csv：CSV 的 detail 只有列名 + 行数 + 前几行样本，本身就
    # 不会大；会撑爆上下文的是把整份内容放进 detail 的那几类（文本/JSON/PDF）。
    path = tmp_path / "big.txt"
    path.write_text("x" * 60000, encoding="utf-8")
    out = as_tool_output("big.txt", ingest(path))
    assert "已截断" in out
