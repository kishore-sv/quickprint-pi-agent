"""Map PrintSettings to CUPS lp -o options."""

from __future__ import annotations

from app.models import PrintSettings
from app.page_range import validate_page_range


def validate_print_settings(settings: PrintSettings) -> None:
    if settings.copies < 1 or settings.copies > 99:
        raise ValueError(f"copies must be 1-99, got {settings.copies}")
    if settings.pages_per_sheet < 1 or settings.pages_per_sheet > 16:
        raise ValueError(
            f"pages_per_sheet must be 1-16, got {settings.pages_per_sheet}"
        )
    if settings.color_mode not in ("bw", "color"):
        raise ValueError(f"Unsupported color_mode: {settings.color_mode}")
    if settings.order not in ("normal", "reverse"):
        raise ValueError(f"Unsupported order: {settings.order}")
    if settings.orientation not in ("auto", "portrait", "landscape"):
        raise ValueError(f"Unsupported orientation: {settings.orientation}")
    validate_page_range(settings.page_range)


def build_lp_options(settings: PrintSettings) -> list[str]:
    """Return flat list of -o key=value tokens (without leading -o)."""
    validate_print_settings(settings)
    options: list[str] = []

    if settings.paper_size:
        options.append(f"media={settings.paper_size}")

    if settings.color_mode == "bw":
        options.append("print-color-mode=monochrome")
    elif settings.color_mode == "color":
        options.append("print-color-mode=color")

    if settings.duplex:
        options.append("sides=two-sided-long-edge")
    else:
        options.append("sides=one-sided")

    if settings.pages_per_sheet > 1:
        options.append(f"number-up={settings.pages_per_sheet}")

    if settings.orientation == "portrait":
        options.append("orientation-requested=3")
    elif settings.orientation == "landscape":
        options.append("orientation-requested=4")

    options.append(f"fit-to-page={'true' if settings.fit_to_page else 'false'}")

    if settings.order == "reverse":
        options.append("outputorder=reverse")
    else:
        options.append("outputorder=normal")

    page_range = validate_page_range(settings.page_range)
    if page_range:
        options.append(f"page-ranges={page_range}")

    return options


def build_lp_argv(
    printer_name: str, file_path: str, settings: PrintSettings
) -> list[str]:
    """Build full lp argument list."""
    argv = ["lp", "-d", printer_name]
    if settings.copies > 1:
        argv.extend(["-n", str(settings.copies)])
    for opt in build_lp_options(settings):
        argv.extend(["-o", opt])
    argv.append(file_path)
    return argv
