from app.cups_options import build_lp_argv, build_lp_options
from app.models import PrintSettings


def test_build_options_bw_a4():
    settings = PrintSettings(
        copies=2,
        color_mode="bw",
        paper_size="A4",
        duplex=True,
        pages_per_sheet=2,
        orientation="portrait",
        fit_to_page=True,
        page_range="1-3",
    )
    opts = build_lp_options(settings)
    assert "media=A4" in opts
    assert "print-color-mode=monochrome" in opts
    assert "sides=two-sided-long-edge" in opts
    assert "number-up=2" in opts
    assert "page-ranges=1-3" in opts


def test_lp_argv():
    argv = build_lp_argv("OfficePrinter", "/tmp/a.pdf", PrintSettings(copies=2))
    assert argv[0] == "lp"
    assert "-d" in argv and "OfficePrinter" in argv
    assert "-n" in argv and "2" in argv
    assert argv[-1] == "/tmp/a.pdf"
