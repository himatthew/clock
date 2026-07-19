import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from resource_config import resolve_pdf_asset, PARENTID_OPTIONS


def test_pdf_asset_default_naming():
    # 文件名已预处理为 日期_原文件名
    fields, src = resolve_pdf_asset("/any/assets/2026-07-17_fur_elise.pdf")
    assert fields["title"] == "2026-07-17_fur_elise"
    assert fields["intro"] == "2026-07-17_fur_elise"
    assert fields["file"] == "/any/assets/2026-07-17_fur_elise.pdf"
    assert fields["parentId"] == PARENTID_OPTIONS["综合资源"]
    assert fields["rtype"] == PARENTID_OPTIONS["综合资源"]
    assert src == "pdf-asset 2026-07-17_fur_elise"


def test_pdf_asset_title_override():
    fields, src = resolve_pdf_asset("/any/assets/2026-07-17_fur_elise.pdf",
                                    title="自定义名")
    assert fields["title"] == "自定义名"
    assert fields["intro"] == "自定义名"


def test_pdf_asset_title_and_intro_override():
    fields, src = resolve_pdf_asset("/any/assets/2026-07-17_fur_elise.pdf",
                                    title="T", intro="I")
    assert fields["title"] == "T"
    assert fields["intro"] == "I"


if __name__ == "__main__":
    test_pdf_asset_default_naming()
    test_pdf_asset_title_override()
    test_pdf_asset_title_and_intro_override()
    print("ALL TESTS PASSED")
