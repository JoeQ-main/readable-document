# Readable Document Viewer — Design Spec

Date: 2026-10-16
Status: draft for review

## 1. Purpose

A small Windows tray utility. When the user clicks **Read document** in its
tray menu, it finds the document window they most recently had in front (a PDF
or a text-heavy image), extracts its text, and opens a new window showing a
temporary, restyled version that is easier to focus on and skim. A **Save**
button writes that version as a standalone HTML file; nothing is written to
disk otherwise.

Audience for the restyling: readers who want focus and skimmability (ADHD-style
reading). The text is never reworded or summarized; only its presentation
changes.

## 2. Scope

In scope:

- Tray icon with menu: Read document, Quit.
- Source detection: last non-shell foreground window.
- File recovery from that window (command line, then window title + search).
- Fallback: capture only that window (PrintWindow) and OCR it.
- Text extraction from PDFs (text layer, or OCR for scanned pages) and from
  image files (PNG, JPG, JPEG, BMP, TIF, TIFF, WEBP, GIF).
- A readability transform producing one self-contained HTML page.
- A pywebview reading window with live toggles and Save as HTML.
- Persisted toggle preferences.
- Clear error messages; the tray keeps running after any error.

Out of scope (YAGNI):

- Global hotkey.
- Saving as PDF or any format other than HTML.
- Editing, summarizing, translating or rewording text.
- Non-Windows platforms.
- Multi-column layout reconstruction beyond PyMuPDF's natural reading order.
- Tables and figures: tables are emitted as plain paragraphs/lines; figures are
  ignored.

## 3. User flow

1. User launches `ReadableDocument.pyw` (or a shortcut to it). A tray icon
   appears. Nothing else happens.
2. User views a PDF or image in any application.
3. User clicks the tray icon → **Read document**.
4. Within a few seconds a window titled `Readable: <name>` opens with the
   restyled text. A header line states the source (file path, or "captured
   from window: <title>" with an "OCR text, may contain errors" note).
5. User adjusts toggles (text size, line spacing, column width, dark mode,
   number highlighting, bionic bolding). Choices persist for next time.
6. User optionally clicks **Save**, picks a location in the native Save As
   dialog (default `<name>-readable.html` in Documents), and a standalone HTML
   file is written with current toggle state baked in.
7. Closing the window discards the document. Several windows can be open at
   once.

## 4. Architecture

Python 3.14, Windows only. All dependencies have Python 3.14 wheels (verified
2026-10-16).

```
pdf_helper/
  __main__.py        entry: starts tray thread, runs pywebview main loop
  app.py             orchestrates one "Read document" pass; routes errors
  tray.py            pystray icon + menu; foreground-window poller
  window_finder.py   candidate window -> SourceDocument (file path or capture)
  capture.py         PrintWindow capture of one hwnd -> PIL.Image
  extract/
    model.py         Block dataclass (kind, level, text), Document dataclass
    pdf.py           PyMuPDF -> blocks (text layer or OCR fallback per page)
    ocr.py           Windows OCR (winocr) -> lines -> blocks
    layout.py        shared line-grouping / heading heuristics
  readable/
    transform.py     Document -> HTML string
    template.html    page skeleton, inline CSS and JS (toolbar, outline, save)
  viewer.py          pywebview window, JS bridge (save, load/store prefs)
  settings.py        read/write %APPDATA%\PDFHelper\settings.json
  errors.py          UserFacingError and message box helper
tests/
  fixtures/          sample.pdf (generated), sample.png (rendered from it)
  test_*.py
ReadableDocument.pyw   launcher without console
requirements.txt
README.md
```

Dependencies: `pymupdf`, `pywebview`, `pystray`, `pillow`, `pywin32`,
`psutil`, `winocr` (pulls the `winrt-*` split packages), `pytest` (dev).

Threading: pywebview must own the main thread. `__main__` creates a hidden
placeholder window and calls `webview.start(func=start_tray)`; `start_tray`
runs `pystray.Icon.run_detached()`. Tray callbacks run the extraction on a
worker thread, then create the reading window via `webview.create_window`
(safe after `start`). This is the first thing verified during implementation;
if `run_detached` misbehaves, the fallback is running pystray on the main
thread and pywebview on a dedicated thread with its own `start()`.

## 5. Component design

### 5.1 Foreground tracking (tray.py)

A daemon thread polls `GetForegroundWindow()` every 500 ms. A window is
recorded as the **candidate** if all hold:

- it is visible and has a non-empty title;
- its window class is not one of `Shell_TrayWnd`, `Progman`, `WorkerW`,
  `Windows.UI.Core.CoreWindow` (Start/search), `NotifyIconOverflowWindow`;
- its process is not the app's own process.

Only the most recent candidate is kept (hwnd, title, pid, class).

### 5.2 Source resolution (window_finder.py)

Input: candidate. Output: `SourceDocument` = either `FileSource(path)` or
`CaptureSource(hwnd, title)`.

Resolution order:

1. **Command line.** Read the process's command line (psutil). Any argument
   that is an existing file with a supported extension → `FileSource`.
2. **Title lookup.** Regex the window title for `<name>.<ext>` with a
   supported extension (case-insensitive, first match). Search, in order:
   a. Windows Recent Items (`%APPDATA%\Microsoft\Windows\Recent\*.lnk`),
      resolving shortcuts via pywin32 and matching on target basename;
   b. `Downloads`, `Desktop`, `Documents` recursively to depth 2.
   Among matches, newest modification time wins.
3. **Capture.** `CaptureSource(hwnd, title)`.

Supported extensions: `.pdf .png .jpg .jpeg .bmp .tif .tiff .webp .gif`.

If there is no candidate: raise `UserFacingError("No document window found.
Open a PDF or image, then click Read document.")`.

### 5.3 Window capture (capture.py)

- Get the window rectangle with `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`
  (falls back to `GetWindowRect`).
- Create a compatible bitmap and call `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)`.
  This renders only that window's content; overlapping windows are excluded.
- If PrintWindow returns 0 or the bitmap is all one color, bring the window to
  the foreground, wait 300 ms, and grab its rectangle from the screen as a
  last resort (this may include overlapping windows; the header line then says
  "screen region capture").
- Result is an in-memory `PIL.Image`; never written to disk.
- If the captured area is smaller than 200×200 px → `UserFacingError`.

### 5.4 Block model (extract/model.py)

```python
@dataclass
class Block:
    kind: Literal["heading", "paragraph", "list_item"]
    text: str
    level: int = 0        # headings: 1..3; list items: nesting (0 for now)

@dataclass
class Document:
    title: str                      # file stem or window title
    source_label: str               # shown in header line
    blocks: list[Block]
    via_ocr: bool
```

### 5.5 PDF extraction (extract/pdf.py)

For each page, `page.get_text("dict")`:

- Collect spans with size, flags (bold bit), text, bbox.
- **Body size** = font size with the highest character count, rounded to 0.5pt.
- A **line** inherits the size of its longest span and is bold if ≥ 60% of
  its characters are in bold spans.
- **Running header/footer removal:** normalize each line's text (strip,
  collapse digits to `#`); any normalized line that appears on ≥ 3 pages and
  sits in the top or bottom 10% of the page is dropped. Lines that are only a
  page number are dropped.
- **Heading:** line size ≥ body × 1.15 and ≤ 120 chars, OR bold and ≤ 80 chars
  and followed by a vertical gap. Level: size ≥ body×1.6 → 1; ≥ 1.3 → 2;
  else 3.
- **List item:** line starts with `•`, `-`, `–`, `*`, `o`, or `\d+[.)]` /
  `[a-z][.)]` followed by a space. Marker is removed.
- **Paragraph assembly:** consecutive non-heading, non-list lines merge into
  one paragraph while the vertical gap between them is < 0.6 × line height.
  Hyphenated line ends (`word-` + lowercase start) are joined without the
  hyphen; otherwise lines join with a space.
- **Scanned page:** if a page yields < 50 characters of text, render it at
  2× (`page.get_pixmap(matrix=Matrix(2,2))`), OCR via `extract/ocr.py`, and
  mark `via_ocr=True` for the document.
- Pages are processed in order; blocks concatenate.

### 5.6 OCR extraction (extract/ocr.py, extract/layout.py)

- `winocr.recognize_pil_sync(image, lang="en")` → lines with text and bbox
  (words aggregated).
- Lines are sorted top-to-bottom, left-to-right.
- `layout.group_lines(lines)` (shared with 5.5's gap logic):
  - median line height `h`;
  - heading if line height ≥ 1.3 × h and ≤ 120 chars, or the line is ≤ 60
    chars, all caps, and ≥ 3 letters;
  - list item by the same marker rule as 5.5;
  - paragraphs merge while vertical gap < 0.6 × h.
- If the OCR engine reports no available language → `UserFacingError`
  explaining: Settings → Time & language → Language & region → add English →
  Options → install OCR.
- If the result has < 20 characters total → `UserFacingError("No readable
  text was found.")`.

### 5.7 Readability transform (readable/transform.py)

Input: `Document`. Output: HTML string (template with placeholders filled;
all text HTML-escaped).

Content rules:

- Headings → `<h1>`..`<h3>` with an `id` (slug + index) and an entry in the
  outline list.
- Paragraphs: split at sentence boundaries (period, `!` or `?`, optional
  closing quote/bracket, whitespace, then an uppercase letter, digit, quote
  or opening bracket) into chunks of at most 4 sentences; each chunk becomes
  its own `<p>`.
- Each `<p>` wraps its first N words in `<b class="lead">` where N = 5, but
  the lead never exceeds 40% of the paragraph's words (minimum 1 word).
- Numbers, percentages, currency amounts and dates (numeric `d/m/yyyy` style
  and month-name dates) wrap in `<mark class="num">`.
- Bionic mode is applied in JS at toggle time (bold first ~40% of each word's
  letters, minimum 1, maximum 4), wrapping the originals so it can be undone.
- List items → `<ul><li>`, consecutive items grouped into one list.
- Header line: `source_label`, plus "OCR text — may contain errors" when
  `via_ocr`.

Style defaults (CSS custom properties, changed by the toolbar):

- `--size: 19px; --leading: 1.75; --measure: 62ch;`
- Light: background `#FAF7F0`, text `#2B2B2B`, heading accent `#2F6F9F`,
  number tint `#FFF3C4`. Dark: background `#1E1E1E`, text `#E6E6E6`,
  accent `#7FB3D5`, tint `#4A4A2A`.
- Font stack: `"Segoe UI", system-ui, sans-serif`.
- Paragraph margin `1.1em 0`; headings `margin-top: 2em`, left 4px accent bar.
- Outline panel: fixed left, collapsible, lists headings as anchor links.
- Toolbar: fixed top; buttons A−/A+, spacing, width, dark, numbers, bionic,
  Save.

JS in the template:

- Applies prefs from `window.pywebview.api.get_prefs()` on load, writes back
  via `set_prefs` on each change. When no `pywebview` object exists (saved
  file opened in a browser) it uses the values baked into the file and
  hides Save.
- `save()` writes current prefs into the root element's `style` attribute,
  then calls `window.pywebview.api.save(...)` with the page's full outer HTML.

### 5.8 Viewer (viewer.py)

- `open_document(doc)`: builds HTML, then `webview.create_window` with title
  `Readable: <doc.title>`, the HTML string, a `js_api=Api(doc)` bridge, and a
  960×1000 size.
- `Api.save(html)`: native save dialog (`create_file_dialog(SAVE_DIALOG)`)
  starting in Documents with filename `<doc.title>-readable.html`; writes
  UTF-8. Returns the path or `None` if cancelled.
- `Api.get_prefs()` / `Api.set_prefs(dict)` delegate to settings.py.

### 5.9 Settings (settings.py)

`%APPDATA%\PDFHelper\settings.json` with keys `size`, `leading`, `measure`,
`dark`, `numbers`, `bionic`. Missing file or bad JSON → defaults.

### 5.10 Orchestration and errors (app.py, errors.py)

`run_read_pass(candidate)`:

1. resolve source (5.2) →
2. extract: `FileSource` with `.pdf` → `pdf.extract`; image → `ocr.extract`;
   `CaptureSource` → capture (5.3) then `ocr.extract` →
3. `viewer.open_document`.

Any `UserFacingError` → Windows message box (`MessageBoxW` via ctypes) with
the message. Any other exception → message box "Something went wrong:
<type>: <msg>" and a traceback appended to `%APPDATA%\PDFHelper\error.log`.
The tray never exits because of a read pass.

## 6. Testing

Unit tests (pytest), pure functions only, no GUI:

- `test_layout.py`: heading/list/paragraph grouping from synthetic line
  records (gaps, heights, caps).
- `test_pdf.py`: body-size detection, heading levels, hyphen joining, running
  header removal, on `fixtures/sample.pdf` (generated by a fixture script with
  PyMuPDF: title, two heading levels, bullets, a repeated footer, 3 pages).
- `test_ocr_layout.py`: OCR line records → blocks (engine itself not called).
- `test_window_finder.py`: title regex; search order and newest-wins using
  `tmp_path` folders injected in place of Recent/Downloads/etc.
- `test_transform.py`: sentence splitting into ≤4-sentence chunks, lead-in
  bolding limits, number marking, HTML escaping, outline generation, list
  grouping.
- `test_settings.py`: defaults on missing/corrupt file, round trip.

Manual smoke test checklist (README): tray appears; PDF in Edge → file found;
PDF in SumatraPDF → file found via command line; PNG in Photos → OCR; web page
→ window capture + OCR; Save produces a file that opens in a browser with the
same look; toggles persist across runs; each error path shows a message and
the tray survives.

## 7. Risks and mitigations

- pywebview/pystray thread ownership (see §4). Verified first.
- Browsers may not expose the PDF filename in the title (e.g. a PDF whose
  metadata title differs). Falls through to capture; acceptable.
- Windows OCR language pack absent on some installs → explicit message.
- PrintWindow returns black for some GPU-accelerated windows → screen-region
  fallback with an explicit label in the header.
- Multi-column PDFs may interleave columns; out of scope beyond PyMuPDF's
  default ordering.
