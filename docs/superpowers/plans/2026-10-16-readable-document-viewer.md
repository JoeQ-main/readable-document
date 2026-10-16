# Readable Document Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Windows tray app that, on "Read document", finds the document window last in front, extracts its text (PDF text layer, or Windows OCR for images/captures), and opens a restyled, skim-friendly reading window with Save-as-HTML.

**Architecture:** A pipeline of pure modules: window → `SourceDocument` (`window_finder`), source → `Document` of `Block`s (`extract/`), `Document` → HTML string (`readable/transform`), HTML → pywebview window (`viewer`). `tray` and `app` glue them; `errors` turns failures into message boxes. pywebview owns the main thread; pystray runs detached on another.

**Tech Stack:** Python 3.14 (Windows), pymupdf, pywebview, pystray, pillow, pywin32, psutil, winocr (+ winrt-* split packages), pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-readable-document-design.md`

## Global Constraints

- Python 3.14, Windows only; every dependency pinned in `requirements.txt` to a version with a 3.14 wheel (verified 2026-10-16: pymupdf 1.28.2, pywebview 6.2.1, pystray 0.19.5, pillow 12.3.0, pywin32 312, winocr 0.0.15, psutil latest, pytest latest).
- Supported extensions: `.pdf .png .jpg .jpeg .bmp .tif .tiff .webp .gif`.
- Text is never reworded or summarized; only restyled.
- The document is never written to disk except by Save; captures stay in memory.
- Settings file: `%APPDATA%\PDFHelper\settings.json`; error log: `%APPDATA%\PDFHelper\error.log`.
- Pref keys and defaults: `size=19`, `leading=1.75`, `measure=62`, `dark=False`, `numbers=True`, `bionic=False`.
- All user-visible errors are `UserFacingError`; the tray never exits because of a read pass.
- Tests are pure (no GUI, no OCR engine, no real windows); GUI pieces get a manual smoke test.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. A PDF with a blank page, or only images on a page, must not crash body-size detection (no spans → no division); the page yields no blocks or goes to OCR. Test added to Task 4.
2. Window titles like `my.report.v2.pdf - Microsoft Edge`, `REPORT.PDF`, or `C:\Users\x\report.pdf - SumatraPDF` must yield the bare filename, never a path fragment. Tests added to Task 6.
3. A settings file with wrong value types (`"size": "big"`) must fall back per key, not reset everything or crash. Test added to Task 1.
4. OCR returning zero or one line must not crash median-height logic; zero lines → `No readable text` error, one line → one paragraph. Tests added to Task 2 and Task 5.
5. A document title containing `: ? * / \ " < > |` (window titles often do) must become a safe default Save filename. Test added to Task 8.

---

### Task 1: Project scaffold and settings

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`, `pdf_helper/__init__.py`, `pdf_helper/extract/__init__.py`, `pdf_helper/readable/__init__.py`, `pdf_helper/errors.py`, `pdf_helper/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `settings.DEFAULTS: dict`, `settings.settings_path() -> Path`, `settings.load_prefs(path: Path | None = None) -> dict`, `settings.save_prefs(prefs: dict, path: Path | None = None) -> dict` (returns the sanitized merged dict), `errors.UserFacingError(Exception)`, `errors.app_data_dir() -> Path` (`%APPDATA%\PDFHelper`, created on demand).

- [ ] **Step 1: Scaffold.** `requirements.txt` listing `pymupdf==1.28.2 pywebview==6.2.1 pystray==0.19.5 pillow==12.3.0 pywin32==312 psutil winocr==0.0.15`; `requirements-dev.txt` with `-r requirements.txt` and `pytest`; `pytest.ini` with `testpaths = tests`; `.gitignore` with `__pycache__/ .pytest_cache/ *.pyc .venv/`. Empty `__init__.py` files. Run `python -m pip install -r requirements-dev.txt` and confirm `python -c "import fitz, webview, pystray, winocr, psutil, win32gui"` prints nothing.

- [ ] **Step 2: Write failing tests** in `tests/test_settings.py`:

```python
def test_missing_file_returns_defaults(tmp_path):
    assert load_prefs(tmp_path / "none.json") == DEFAULTS

def test_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "s.json"; p.write_text("{not json")
    assert load_prefs(p) == DEFAULTS

def test_wrong_types_fall_back_per_key(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"size": "big", "dark": true, "bogus": 1}')
    prefs = load_prefs(p)
    assert prefs["size"] == 19 and prefs["dark"] is True and "bogus" not in prefs

def test_round_trip(tmp_path):
    p = tmp_path / "s.json"
    save_prefs({"size": 22, "bionic": True}, p)
    prefs = load_prefs(p)
    assert prefs["size"] == 22 and prefs["bionic"] is True and prefs["leading"] == 1.75
```

- [ ] **Step 3: Run** `pytest tests/test_settings.py -v` → FAIL (import error).

- [ ] **Step 4: Implement** `errors.py` (`UserFacingError`, `app_data_dir()`) and `settings.py`. Type rule: a value is accepted only if `isinstance(value, type(DEFAULTS[key]))` with bool checked before int; `size` and `measure` accept int, `leading` accepts int or float. `save_prefs` merges over `load_prefs(path)`, writes JSON with `indent=2`, creating the parent directory.

- [ ] **Step 5: Run** `pytest tests/test_settings.py -v` → PASS.

- [ ] **Step 6: Commit** `feat: scaffold project and settings store`.

---

### Task 2: Block model and layout heuristics

**Files:**
- Create: `pdf_helper/extract/model.py`, `pdf_helper/extract/layout.py`, `tests/__init__.py`, `tests/helpers.py`
- Test: `tests/test_layout.py`

`tests/helpers.py` holds the shared test helpers later tasks import: `L(text, y, h=10, size=None, bold=False, x0=0) -> Line` building `Line(text, x0, y, x0 + 10*len(text), y + h, size, bold)`, and `FIXTURES = Path(__file__).parent / "fixtures"`.

**Interfaces:**
- Produces:
  - `model.Block(kind: Literal["heading","paragraph","list_item"], text: str, level: int = 0)`
  - `model.Document(title: str, source_label: str, blocks: list[Block], via_ocr: bool)`
  - `layout.Line(text: str, x0: float, y0: float, x1: float, y1: float, size: float | None = None, bold: bool = False)` with property `height`
  - `layout.strip_list_marker(text: str) -> str | None` (stripped text if a list marker leads, else `None`)
  - `layout.group_lines(lines: list[Line], body_size: float | None = None) -> list[Block]`
  - `layout.merge_paragraph_runs(groups: list[list[Block]]) -> list[Block]` (joins the last paragraph of one group with the first of the next when the next starts with a lowercase letter; used for page boundaries)

- [ ] **Step 1: Write failing tests** in `tests/test_layout.py`. Helper `L(text, y, h=10, size=None, bold=False, x0=0)` builds a `Line` with `y0=y, y1=y+h, x1=x0+10*len(text)`.

```python
def test_empty_input():
    assert group_lines([]) == []

def test_single_line_is_paragraph():
    assert group_lines([L("Just one line.", 0)]) == [Block("paragraph", "Just one line.")]

def test_close_lines_merge_into_paragraph():
    # gap 2 < 0.6*10
    blocks = group_lines([L("First part", 0), L("second part.", 12)])
    assert blocks == [Block("paragraph", "First part second part.")]

def test_wide_gap_splits_paragraphs():
    blocks = group_lines([L("One.", 0), L("Two.", 30)])
    assert [b.text for b in blocks] == ["One.", "Two."]

def test_hyphen_join():
    blocks = group_lines([L("exam-", 0), L("ple text", 12)])
    assert blocks[0].text == "example text"

def test_pdf_heading_by_size():
    blocks = group_lines([L("Title", 0, size=20), L("Body text here.", 30, size=10)], body_size=10)
    assert blocks[0] == Block("heading", "Title", 1)       # 20 >= 1.6*10
    blocks = group_lines([L("Sub", 0, size=14), L("Body.", 30, size=10)], body_size=10)
    assert blocks[0].level == 2                            # 14 >= 1.3*10
    blocks = group_lines([L("Minor", 0, size=11.5), L("Body.", 30, size=10)], body_size=10)
    assert blocks[0].level == 3                            # 11.5 >= 1.15*10

def test_pdf_bold_short_line_followed_by_gap_is_heading():
    blocks = group_lines([L("Bold lead", 0, size=10, bold=True), L("Body.", 30, size=10)], body_size=10)
    assert blocks[0].kind == "heading" and blocks[0].level == 3

def test_pdf_bold_line_without_gap_is_not_heading():
    blocks = group_lines([L("Bold lead", 0, size=10, bold=True), L("continues.", 12, size=10)], body_size=10)
    assert blocks[0].kind == "paragraph"

def test_pdf_long_large_line_is_not_heading():
    blocks = group_lines([L("x" * 121, 0, size=20), L("Body.", 40, size=10)], body_size=10)
    assert blocks[0].kind == "paragraph"

def test_ocr_heading_by_height():
    blocks = group_lines([L("Big", 0, h=14), L("normal", 30), L("normal", 42), L("normal", 54)])
    assert blocks[0] == Block("heading", "Big", 2)         # 14 >= 1.3*10, < 1.6*10

def test_ocr_all_caps_short_line_is_heading():
    blocks = group_lines([L("SECTION TWO", 0), L("normal text", 30)])
    assert blocks[0] == Block("heading", "SECTION TWO", 3)

def test_list_items():
    assert strip_list_marker("• apples") == "apples"
    assert strip_list_marker("1. apples") == "apples"
    assert strip_list_marker("a) apples") == "apples"
    assert strip_list_marker("o apples") == "apples"
    assert strip_list_marker("-apples") is None
    assert strip_list_marker("plain") is None
    blocks = group_lines([L("• one", 0), L("• two", 12)])
    assert blocks == [Block("list_item", "one"), Block("list_item", "two")]

def test_merge_paragraph_runs_joins_lowercase_continuation():
    g1 = [Block("paragraph", "ends mid")]
    g2 = [Block("paragraph", "sentence here."), Block("heading", "Next", 1)]
    assert merge_paragraph_runs([g1, g2]) == [Block("paragraph", "ends mid sentence here."), Block("heading", "Next", 1)]

def test_merge_paragraph_runs_keeps_capitalized_start_separate():
    out = merge_paragraph_runs([[Block("paragraph", "Done.")], [Block("paragraph", "New.")]])
    assert len(out) == 2
```

- [ ] **Step 2: Run** `pytest tests/test_layout.py -v` → FAIL (import error).

- [ ] **Step 3: Implement** `model.py` (frozen dataclasses) and `layout.py`. Decisions the tests leave open:
  - Reference height for OCR mode: median of `line.height`; for PDF mode use `body_size` for heading ratios and each line's own `height` for gap tests.
  - Gap between consecutive lines: `next.y0 - prev.y1`; "followed by a gap" = gap ≥ 0.6 × `prev.height` or last line.
  - Heading levels: ratio = `size/body_size` (PDF) or `height/median` (OCR); ≥1.6 → 1, ≥1.3 → 2, else 3. Bold-short and all-caps headings are level 3.
  - All-caps rule: ≤ 60 chars, ≥ 3 letters, `text.upper() == text`.
  - List marker regex: `^(?:[•\-–*o]|\d+[.)]|[a-z][.)])\s+`.
  - Hyphen join: previous text ends with `-` and next text starts with a lowercase letter → concatenate without the hyphen.
  - A list item line never merges with the following line.

- [ ] **Step 4: Run** `pytest tests/test_layout.py -v` → PASS.

- [ ] **Step 5: Commit** `feat: block model and line grouping heuristics`.

---

### Task 3: Readability transform and HTML template

**Files:**
- Create: `pdf_helper/readable/transform.py`, `pdf_helper/readable/template.html`
- Test: `tests/test_transform.py`

**Interfaces:**
- Consumes: `model.Block`, `model.Document`.
- Produces:
  - `transform.split_sentences(text: str) -> list[str]`
  - `transform.chunk_paragraph(text: str, max_sentences: int = 4) -> list[str]`
  - `transform.mark_lead(escaped_text: str) -> str`
  - `transform.mark_numbers(html: str) -> str`
  - `transform.slugify(text: str) -> str`
  - `transform.render(doc: Document, prefs: dict) -> str` (complete HTML page)
- Template contract (JS side, used by Task 8): prefs live as CSS custom properties on `<html>`: `--size: {size}px; --leading: {leading}; --measure: {measure}ch;` and data attributes `data-dark`, `data-numbers`, `data-bionic` (`"1"`/`"0"`). JS reads `window.pywebview.api.get_prefs()`, writes `set_prefs(obj)`, and `save()` calls `window.pywebview.api.save(html)`. When `window.pywebview` is undefined (saved file in a browser) the Save button is hidden and the baked values are used.

- [ ] **Step 1: Write failing tests** in `tests/test_transform.py`:

```python
def test_split_sentences():
    assert split_sentences('One. Two! "Three?" Four 5.') == ["One.", "Two!", '"Three?"', "Four 5."]

def test_split_keeps_abbreviation_like_lowercase_continuation():
    assert split_sentences("e.g. this stays. Next one.") == ["e.g. this stays.", "Next one."]

def test_chunk_paragraph_max_four_sentences():
    text = " ".join(f"Sentence {i}." for i in range(9))
    chunks = chunk_paragraph(text)
    assert len(chunks) == 3 and chunks[0].count(".") == 4 and chunks[2] == "Sentence 8."

def test_chunk_paragraph_without_terminators_is_kept_whole():
    text = "no punctuation at all " * 30
    assert chunk_paragraph(text) == [text.strip()]

def test_mark_lead_five_words_capped_at_forty_percent():
    assert mark_lead("a b c d e f g h i j k l m") == '<b class="lead">a b c d e</b> f g h i j k l m'
    assert mark_lead("one two three four five") == '<b class="lead">one two</b> three four five'
    assert mark_lead("one") == '<b class="lead">one</b>'

def test_mark_numbers():
    assert mark_numbers("Up 12.5% to $3,400 by 4/15/2026 and March 3, 2026.") == (
        'Up <mark class="num">12.5%</mark> to <mark class="num">$3,400</mark> by '
        '<mark class="num">4/15/2026</mark> and <mark class="num">March 3, 2026</mark>.')

def test_mark_numbers_ignores_tag_attributes():
    assert mark_numbers('<b class="lead">In 2020</b>') == '<b class="lead">In <mark class="num">2020</mark></b>'

def test_render_escapes_and_structures(sample_doc):
    html = render(sample_doc, DEFAULTS)
    assert "&lt;script&gt;" in html and "<script>alert" not in html
    assert '<h1 id="intro-0">Intro</h1>' in html
    assert '<a href="#intro-0">Intro</a>' in html           # outline entry
    assert "<ul><li>one</li><li>two</li></ul>" in html.replace("\n", "")
    assert "--size: 19px" in html and 'data-dark="0"' in html
    assert "OCR text" not in html

def test_render_ocr_note_and_source(sample_doc):
    doc = replace(sample_doc, via_ocr=True, source_label="captured from window: Foo")
    html = render(doc, DEFAULTS)
    assert "OCR text" in html and "captured from window: Foo" in html

def test_render_no_headings_hides_outline(sample_doc):
    doc = replace(sample_doc, blocks=[Block("paragraph", "Only text.")])
    assert 'class="outline hidden"' in render(doc, DEFAULTS)
```

`sample_doc` is a fixture in `tests/conftest.py` (created in this task, reused by Task 8): `Document("Sample", "C:/x/sample.pdf", [Block("heading","Intro",1), Block("paragraph","Hello <script>alert(1)</script> world. Two. Three. Four. Five."), Block("list_item","one"), Block("list_item","two")], False)`.

- [ ] **Step 2: Run** `pytest tests/test_transform.py -v` → FAIL.

- [ ] **Step 3: Implement `transform.py`.** Decisions:
  - Sentence boundary: Python's `re` needs fixed-width lookbehinds, so split on `(?:(?<=[.!?])|(?<=[.!?]["')\]]))\s+(?=["(\[]?[A-Z0-9])` with `re.split`; strip the input first and each part after.
  - `chunk_paragraph`: group `split_sentences` output into runs of `max_sentences`; a text with one sentence returns `[text.strip()]`.
  - Per paragraph block, order of operations: `chunk_paragraph` on the raw text → for each chunk `html.escape(chunk, quote=False)` → `mark_lead` → `mark_numbers` → `<p>`. Quoting is off so `&#x27;` never appears and its digits are not marked.
  - `mark_lead`: N = `min(5, max(1, floor(0.4 * word_count)))` on whitespace-split words.
  - `mark_numbers` runs only on text outside tags: split on `(<[^>]+>)` and transform only the non-tag segments, each in a single `re.sub` with one combined alternation so an inserted `<mark>` is never re-scanned. Alternatives, in this order: month-name dates `\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}(?:, \d{4})?\b`, numeric dates `\b\d{1,2}/\d{1,2}/\d{2,4}\b`, currency `\$\d[\d,]*(?:\.\d+)?`, numbers `\b\d[\d,]*(?:\.\d+)?%?`.
  - List items: escape and `mark_numbers` only (no lead-in); emit `<ul><li>…</li></ul>` with no indentation whitespace between tags.
  - Heading id: `f"{slugify(text)[:40] or 'h'}-{index}"`, index = running heading count starting at 0; `slugify` lowercases, replaces non-alphanumerics with `-`, strips `-`.
  - Consecutive `list_item` blocks produce one `<ul>`.
  - Fill the template with `str.replace` on placeholders `{{TITLE}} {{SOURCE}} {{OCR_NOTE}} {{OUTLINE}} {{BODY}} {{ROOT_STYLE}} {{DATA_ATTRS}} {{PREFS_JSON}}` (never `str.format`; the template contains braces).

- [ ] **Step 4: Write `template.html`.** Inline CSS and JS, no external resources. CSS per spec §5.7: light background `#FAF7F0`, text `#2B2B2B`, accent `#2F6F9F`, number tint `#FFF3C4`; dark `#1E1E1E`/`#E6E6E6`/`#7FB3D5`/`#4A4A2A` under `html[data-dark="1"]`; font stack `"Segoe UI", system-ui, sans-serif`; `main { max-width: var(--measure); font-size: var(--size); line-height: var(--leading); margin: 0 auto; padding: 4rem 1rem; }`; `p { margin: 1.1em 0 }`; headings `margin-top: 2em; border-left: 4px solid accent; padding-left: .5em`; `mark.num` tinted only when `data-numbers="1"`; `.outline` fixed left panel listing `{{OUTLINE}}` links with a collapse button, `.hidden` → `display:none`; fixed top toolbar with buttons `A−`, `A+`, `Spacing`, `Width`, `Dark`, `Numbers`, `Bionic`, `Save`. JS: `applyPrefs(p)` sets the CSS variables and data attributes; `size` steps ±2 within 14–32, `leading` cycles 1.5→1.75→2.0, `measure` cycles 50→62→75; `bionic(on)` wraps the first `max(1, min(4, round(0.4*letters)))` letters of each word inside `p`/`li` in `<b class="bio">` and unwraps when off; every change calls `window.pywebview?.api.set_prefs(prefs)`; on `pywebviewready` the page loads prefs via `get_prefs()` and applies them; without `window.pywebview` the Save button gets `hidden`. `save()` first writes the current prefs into the root style/data attributes, then calls `window.pywebview.api.save(document.documentElement.outerHTML)` and shows the returned path (or "Not saved") in a toolbar status span for 3 s.

- [ ] **Step 5: Run** `pytest tests/test_transform.py -v` → PASS. Then open a rendered sample in a browser for a visual check: `python -c "from pdf_helper.readable.transform import render; ..."` writing to the scratchpad, confirm toolbar toggles work without pywebview and Save is hidden.

- [ ] **Step 6: Commit** `feat: readability transform and HTML template`.

---

### Task 4: PDF extraction

**Files:**
- Create: `pdf_helper/extract/pdf.py`, `tests/fixtures/make_fixtures.py`, `tests/fixtures/sample.pdf`, `tests/fixtures/blank_page.pdf`
- Test: `tests/test_pdf.py`

**Interfaces:**
- Consumes: `layout.Line`, `layout.group_lines`, `layout.merge_paragraph_runs`, `model.Document`; `ocr.recognize_image` (Task 5; stub it via a module-level attribute `pdf.ocr_lines: Callable[[Image], list[Line]]` that tests monkeypatch).
- Produces:
  - `pdf.extract(path: Path) -> Document`
  - `pdf.page_lines(page) -> list[Line]`
  - `pdf.body_size(lines: list[Line]) -> float | None`
  - `pdf.remove_running_lines(pages: list[list[Line]], page_heights: list[float]) -> list[list[Line]]`

- [ ] **Step 1: Write the fixture generator** `tests/fixtures/make_fixtures.py` using PyMuPDF: `sample.pdf` with 3 Letter pages; page 1: "Sample Report" at 24pt, "Introduction" at 16pt, three body paragraphs at 11pt (one ending with a hyphenated line break `exam-` / `ple`), a bullet list `• one`, `• two`; pages 2–3: "Methods" / "Results" at 16pt plus body text; every page has footer "Sample Corp Confidential" and "Page N" at the bottom 5%; `blank_page.pdf` with one empty page followed by one text page. Also render page 1 of `sample.pdf` at 2× to `sample.png` for Task 5's manual check. Run it and commit the outputs.

- [ ] **Step 2: Write failing tests** in `tests/test_pdf.py`:

```python
def test_body_size_is_most_common_by_chars():
    lines = [L("x"*50, 0, size=11.0), L("Title", 0, size=24.0), L("y"*5, 0, size=11.2)]
    assert body_size(lines) == 11.0
    assert body_size([]) is None

def test_remove_running_lines_drops_repeated_footers_and_page_numbers():
    pages = [[L("Body", 100), L("Confidential", 780), L(f"Page {i}", 790)] for i in range(3)]
    out = remove_running_lines(pages, [792.0]*3)
    assert all([l.text for l in p] == ["Body"] for p in out)

def test_extract_sample_structure():
    doc = extract(FIXTURES / "sample.pdf")
    kinds = [(b.kind, b.level, b.text) for b in doc.blocks]
    assert kinds[0] == ("heading", 1, "Sample Report")
    assert ("heading", 2, "Introduction") in kinds
    assert any(b.kind == "paragraph" and "example" in b.text for b in doc.blocks)
    assert [b.text for b in doc.blocks if b.kind == "list_item"] == ["one", "two"]
    assert not any("Confidential" in b.text or b.text.startswith("Page ") for b in doc.blocks)
    assert doc.title == "sample" and doc.via_ocr is False

def test_blank_page_does_not_crash_and_uses_ocr_stub(monkeypatch):
    monkeypatch.setattr(pdf, "ocr_lines", lambda img: [])
    doc = extract(FIXTURES / "blank_page.pdf")
    assert doc.blocks and doc.via_ocr is True

def test_scanned_page_goes_through_ocr(monkeypatch):
    monkeypatch.setattr(pdf, "ocr_lines", lambda img: [L("OCR LINE", 0)])
    doc = extract(FIXTURES / "blank_page.pdf")
    assert doc.blocks[0].text == "OCR LINE"
```

- [ ] **Step 3: Run** `pytest tests/test_pdf.py -v` → FAIL.

- [ ] **Step 4: Implement `pdf.py`.** Decisions:
  - `page_lines`: iterate `page.get_text("dict")["blocks"]` → `lines` → `spans`; line size = size of the span with most characters; bold if ≥ 60% of characters are in spans with `flags & 16`; skip whitespace-only lines; bbox from the line.
  - `body_size`: character count per size rounded to 0.5; `None` when no lines.
  - `remove_running_lines`: normalize `re.sub(r"\d+", "#", text.strip().lower())`; drop normalized texts present on ≥ 3 pages whose `y0 < 0.10*height` or `y1 > 0.90*height`; also drop lines matching `^(page\s+)?\d+(\s+of\s+\d+)?$` (case-insensitive).
  - Per page: if the page's total character count < 50 → `img = PIL.Image.frombytes("RGB", (pix.width, pix.height), pix.samples)` from `page.get_pixmap(matrix=fitz.Matrix(2, 2))`, lines = `ocr_lines(img)`, `via_ocr = True`, blocks = `group_lines(lines)`; else blocks = `group_lines(lines, body_size=document_body_size)` where the body size is computed over all text-layer pages together.
  - `ocr_lines` default is `lambda img: __import__("pdf_helper.extract.ocr", fromlist=["recognize_image"]).recognize_image(img)` (lazy import so tests never load winrt).
  - Result blocks = `merge_paragraph_runs(per_page_blocks)`; `title=path.stem`, `source_label=str(path)`.
  - Zero blocks overall → `UserFacingError("No readable text was found.")`.

- [ ] **Step 5: Run** `pytest tests/test_pdf.py -v` → PASS. If heading thresholds misclassify the fixture, adjust the fixture font sizes, not the spec ratios.

- [ ] **Step 6: Commit** `feat: PDF extraction with running-header removal and OCR fallback`.

---

### Task 5: OCR extraction

**Files:**
- Create: `pdf_helper/extract/ocr.py`
- Test: `tests/test_ocr.py`

**Interfaces:**
- Consumes: `layout.Line`, `layout.group_lines`, `model.Document`, `errors.UserFacingError`.
- Produces:
  - `ocr.lines_from_result(result: dict) -> list[Line]` (pure: winocr result dict → lines, sorted by `(y0, x0)`)
  - `ocr.recognize_image(image: PIL.Image.Image) -> list[Line]` (calls `winocr.recognize_pil_sync(image, lang="en")`)
  - `ocr.extract(image: PIL.Image.Image, title: str, source_label: str) -> Document`
  - `ocr.extract_file(path: Path) -> Document`
  - `ocr.recognizer: Callable[[Image], dict]` module attribute, default wraps winocr; tests monkeypatch it.

- [ ] **Step 1: Write failing tests** in `tests/test_ocr.py`:

```python
def word(text, x, y, w=10, h=10):
    return {"text": text, "bounding_rect": {"x": x, "y": y, "width": w, "height": h}}

def test_lines_from_result_unions_word_boxes_and_sorts():
    result = {"lines": [
        {"text": "second line", "words": [word("second", 0, 20), word("line", 60, 20)]},
        {"text": "first line", "words": [word("first", 0, 0), word("line", 50, 0, 20, 12)]}]}
    lines = lines_from_result(result)
    assert [l.text for l in lines] == ["first line", "second line"]
    assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (0, 0, 70, 12)

def test_extract_too_little_text_raises(monkeypatch):
    monkeypatch.setattr(ocr, "recognizer", lambda img: {"lines": [{"text": "hi", "words": [word("hi", 0, 0)]}]})
    with pytest.raises(UserFacingError, match="No readable text"):
        extract(Image.new("RGB", (300, 300)), "t", "s")

def test_extract_single_line_becomes_paragraph(monkeypatch):
    monkeypatch.setattr(ocr, "recognizer", lambda img: {"lines": [{"text": "This is a single long line of text", "words": [word("x", 0, 0, 300, 12)]}]})
    doc = extract(Image.new("RGB", (300, 300)), "t", "s")
    assert doc.blocks == [Block("paragraph", "This is a single long line of text")] and doc.via_ocr

def test_missing_language_pack_is_user_facing(monkeypatch):
    def boom(img): raise AssertionError('Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"')
    monkeypatch.setattr(ocr, "recognizer", boom)
    with pytest.raises(UserFacingError, match="Settings"):
        extract(Image.new("RGB", (300, 300)), "t", "s")
```

- [ ] **Step 2: Run** `pytest tests/test_ocr.py -v` → FAIL.

- [ ] **Step 3: Implement `ocr.py`.** Decisions:
  - `recognizer` default: `lambda img: __import__("winocr").recognize_pil_sync(img, lang="en")` (lazy import).
  - `recognize_image` catches `AssertionError` from the recognizer and raises `UserFacingError("Windows OCR has no English language pack. Install it under Settings → Time & language → Language & region → English → Language options → Basic typing / OCR, or run in an admin PowerShell: Add-WindowsCapability -Online -Name \"Language.OCR~~~en-US~0.0.1.0\"")`.
  - Text threshold: total characters across lines < 20 → `UserFacingError("No readable text was found.")`.
  - Images are converted to RGB before recognition; images wider or taller than 10000 px are downscaled to fit (Windows OCR limit).
  - `extract_file`: `title=path.stem`, `source_label=str(path)`.

- [ ] **Step 4: Run** `pytest tests/test_ocr.py -v` → PASS.

- [ ] **Step 5: Manual check.** `python -c "from pathlib import Path; from pdf_helper.extract.ocr import extract_file; d=extract_file(Path('tests/fixtures/sample.png')); print(*[(b.kind,b.text[:40]) for b in d.blocks], sep='\n')"` → prints the heading "Sample Report" and body paragraphs. Record the result in the commit message.

- [ ] **Step 6: Commit** `feat: Windows OCR extraction`.

---

### Task 6: Window finder (source resolution)

**Files:**
- Create: `pdf_helper/window_finder.py`
- Test: `tests/test_window_finder.py`

**Interfaces:**
- Consumes: `errors.UserFacingError`; `tray.Candidate` is defined here to avoid a cycle (Task 9 imports it from this module).
- Produces:
  - `window_finder.Candidate(hwnd: int, title: str, pid: int, cls: str)` (frozen dataclass)
  - `window_finder.SUPPORTED_EXTS: frozenset[str]`
  - `window_finder.FileSource(path: Path)`, `window_finder.CaptureSource(hwnd: int, title: str)`
  - `window_finder.filename_from_title(title: str) -> str | None`
  - `window_finder.path_from_cmdline(args: list[str]) -> Path | None`
  - `window_finder.find_file_by_name(name: str, recent_dir: Path, search_dirs: list[Path], resolve_link=resolve_shortcut) -> Path | None`
  - `window_finder.resolve_shortcut(lnk: Path) -> Path | None`
  - `window_finder.resolve_source(candidate: Candidate | None, cmdline=psutil_cmdline, recent_dir=None, search_dirs=None) -> FileSource | CaptureSource`

- [ ] **Step 1: Write failing tests** in `tests/test_window_finder.py`:

```python
@pytest.mark.parametrize("title,expected", [
    ("report.pdf - Adobe Acrobat", "report.pdf"),
    ("my.report.v2.pdf - Microsoft Edge", "my.report.v2.pdf"),
    ("REPORT.PDF", "REPORT.PDF"),
    (r"C:\Users\x\report.pdf - SumatraPDF", "report.pdf"),
    ("scan.jpeg – Photos", "scan.jpeg"),
    ("Inbox - Mail", None),
    ("notes.pdfx - Editor", None),
])
def test_filename_from_title(title, expected):
    assert filename_from_title(title) == expected

def test_path_from_cmdline_picks_existing_supported_file(tmp_path):
    f = tmp_path / "a.pdf"; f.write_bytes(b"%PDF")
    assert path_from_cmdline(["viewer.exe", "-flag", str(tmp_path / "missing.pdf"), str(f)]) == f
    assert path_from_cmdline(["viewer.exe", str(tmp_path)]) is None

def test_find_file_by_name_prefers_newest_and_searches_depth_two(tmp_path):
    recent = tmp_path / "recent"; recent.mkdir()
    dl = tmp_path / "Downloads"; (dl / "a" / "b" / "c").mkdir(parents=True)
    old = dl / "a" / "report.pdf"; old.write_bytes(b"1")
    new = dl / "a" / "b" / "report.pdf"; new.write_bytes(b"2")
    deep = dl / "a" / "b" / "c" / "report.pdf"; deep.write_bytes(b"3")
    os.utime(old, (1, 1)); os.utime(new, (2, 2)); os.utime(deep, (3, 3))
    assert find_file_by_name("report.pdf", recent, [dl], resolve_link=lambda p: None) == new

def test_find_file_by_name_uses_recent_links(tmp_path):
    recent = tmp_path / "recent"; recent.mkdir(); (recent / "report.pdf.lnk").write_bytes(b"")
    target = tmp_path / "elsewhere" / "Report.PDF"; target.parent.mkdir(); target.write_bytes(b"x")
    assert find_file_by_name("report.pdf", recent, [], resolve_link=lambda p: target) == target

def test_resolve_source_order(tmp_path):
    c = Candidate(1, "report.pdf - Edge", 42, "Chrome_WidgetWin_1")
    f = tmp_path / "report.pdf"; f.write_bytes(b"x")
    assert resolve_source(c, cmdline=lambda pid: ["msedge.exe"], recent_dir=tmp_path / "none", search_dirs=[tmp_path]) == FileSource(f)
    assert resolve_source(c, cmdline=lambda pid: ["msedge.exe"], recent_dir=tmp_path / "none", search_dirs=[]) == CaptureSource(1, "report.pdf - Edge")
    g = tmp_path / "other.pdf"; g.write_bytes(b"x")
    assert resolve_source(c, cmdline=lambda pid: ["viewer.exe", str(g)], recent_dir=tmp_path / "none", search_dirs=[tmp_path]) == FileSource(g)

def test_resolve_source_without_candidate_raises():
    with pytest.raises(UserFacingError, match="No document window"):
        resolve_source(None)
```

- [ ] **Step 2: Run** `pytest tests/test_window_finder.py -v` → FAIL.

- [ ] **Step 3: Implement `window_finder.py`.** Decisions:
  - Title regex: `([^\\/:*?"<>|\r\n]+?\.(?:pdf|png|jpe?g|bmp|tiff?|webp|gif))(?![\w.])`, `re.IGNORECASE`; take group 1, then keep only the text after the last `\` or `/` (`re.split(r"[\\/]", g)[-1]`) and strip it, so a title that embeds a path still yields the bare filename.
  - `psutil_cmdline(pid)`: `psutil.Process(pid).cmdline()`, returning `[]` on any `psutil.Error`.
  - `resolve_shortcut`: `pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)`, `QueryInterface(pythoncom.IID_IPersistFile).Load(str(lnk))`, `GetPath(shell.SLGP_UNCPRIORITY)[0]`; `None` on any exception.
  - Default `recent_dir` = `%APPDATA%\Microsoft\Windows\Recent`; default `search_dirs` = `~/Downloads`, `~/Desktop`, `~/Documents`.
  - Recent Items: resolve every `*.lnk` whose stem equals `name` case-insensitively (Recent links are named `<filename>.lnk`); keep targets that exist and whose basename matches.
  - Depth-2 search: the directory itself, its children, and their children (`glob` patterns `name`, `*/name`, `*/*/name`), case-insensitive match on basename; newest `st_mtime` wins across Recent and search dirs together.
  - No candidate → `UserFacingError("No document window found. Open a PDF or image, then click Read document.")`.

- [ ] **Step 4: Run** `pytest tests/test_window_finder.py -v` → PASS.

- [ ] **Step 5: Commit** `feat: resolve document source from active window`.

---

### Task 7: Window capture

**Files:**
- Create: `pdf_helper/capture.py`, `scripts/capture_check.py`
- Test: `tests/test_capture.py` (pure parts only)

**Interfaces:**
- Consumes: `errors.UserFacingError`.
- Produces:
  - `capture.window_rect(hwnd: int) -> tuple[int, int, int, int]`
  - `capture.is_flat(image: Image) -> bool` (every band's min == max)
  - `capture.capture_window(hwnd: int) -> tuple[Image, str]` where the string is `"window"` (PrintWindow) or `"screen"` (fallback)

- [ ] **Step 1: Write failing tests** in `tests/test_capture.py`:

```python
def test_is_flat():
    assert is_flat(Image.new("RGB", (10, 10), "black"))
    img = Image.new("RGB", (10, 10), "black"); img.putpixel((0, 0), (255, 255, 255))
    assert not is_flat(img)

def test_too_small_rect_raises(monkeypatch):
    monkeypatch.setattr(capture, "window_rect", lambda h: (0, 0, 150, 300))
    with pytest.raises(UserFacingError, match="too small"):
        capture_window(123)

def test_falls_back_to_screen_when_print_window_is_flat(monkeypatch):
    monkeypatch.setattr(capture, "window_rect", lambda h: (0, 0, 400, 400))
    monkeypatch.setattr(capture, "_print_window", lambda h, w, ht: Image.new("RGB", (400, 400), "black"))
    monkeypatch.setattr(capture, "_grab_screen", lambda h, rect: Image.new("RGB", (400, 400), "white"))
    img, method = capture_window(1)
    assert method == "screen"
```

- [ ] **Step 2: Run** `pytest tests/test_capture.py -v` → FAIL.

- [ ] **Step 3: Implement `capture.py`.** Decisions:
  - `window_rect`: `ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, byref(RECT), sizeof(RECT))` (9 = `DWMWA_EXTENDED_FRAME_BOUNDS`); on nonzero HRESULT fall back to `win32gui.GetWindowRect`.
  - `_print_window(hwnd, w, h) -> Image | None`: `win32gui.GetWindowDC` → `win32ui.CreateDCFromHandle` → `CreateCompatibleDC` → `win32ui.CreateBitmap().CreateCompatibleBitmap(dc, w, h)` → `SelectObject` → `ctypes.windll.user32.PrintWindow(hwnd, memdc.GetSafeHdc(), 2)` (2 = `PW_RENDERFULLCONTENT`); `None` if it returns 0; convert via `bmp.GetBitmapBits(True)` → `Image.frombuffer("RGB", (w, h), bits, "raw", "BGRX", 0, 1)`; always release DCs and delete the bitmap in `finally`.
  - `_grab_screen(hwnd, rect)`: `win32gui.SetForegroundWindow(hwnd)` inside a try/except (it fails when another process holds focus), `time.sleep(0.3)`, then `PIL.ImageGrab.grab(bbox=rect, all_screens=True)`.
  - `capture_window`: rect smaller than 200×200 → `UserFacingError("The window is too small to read.")`; use PrintWindow result unless `None` or `is_flat`; then fall back to the screen grab.
  - Mark the process DPI-aware once at import (`ctypes.windll.shcore.SetProcessDpiAwareness(2)` in a try/except) so rectangles are in physical pixels.

- [ ] **Step 4: Run** `pytest tests/test_capture.py -v` → PASS.

- [ ] **Step 5: Manual check** with `scripts/capture_check.py`: it sleeps 3 s, captures the foreground window via `capture_window(win32gui.GetForegroundWindow())`, and shows it with `image.show()`. Run it, click a Notepad window within 3 s, and confirm only that window appears and the method printed is `window`. Partially cover the window with another one and confirm the capture still shows only Notepad.

- [ ] **Step 6: Commit** `feat: capture a single window for OCR`.

---

### Task 8: Viewer window and Save

**Files:**
- Create: `pdf_helper/viewer.py`
- Test: `tests/test_viewer.py`

**Interfaces:**
- Consumes: `transform.render`, `settings.load_prefs/save_prefs`, `model.Document`.
- Produces:
  - `viewer.safe_filename(title: str) -> str`
  - `viewer.Api(doc: Document, dialog: Callable[[Path, str], Path | None], write=Path.write_text)` with methods `save(html: str) -> str | None`, `get_prefs() -> dict`, `set_prefs(prefs: dict) -> dict`
  - `viewer.open_document(doc: Document) -> webview.Window` (calls `webview.create_window(title=f"Readable: {doc.title}", html=render(doc, load_prefs()), js_api=api, width=960, height=1000)` and stores the window on the api as `api.window`)
  - `viewer.documents_dir() -> Path`

- [ ] **Step 1: Write failing tests** in `tests/test_viewer.py`:

```python
@pytest.mark.parametrize("title,expected", [
    ("report", "report-readable.html"),
    ('Q3: plan? <draft> "final"/v2|x*', "Q3_ plan_ _draft_ _final__v2_x_-readable.html"),
    ("   ", "document-readable.html"),
])
def test_safe_filename(title, expected):
    assert safe_filename(title) == expected

def test_api_save_writes_html_to_chosen_path(tmp_path, sample_doc):
    chosen = tmp_path / "out.html"
    api = Api(sample_doc, dialog=lambda d, name: chosen)
    assert api.save("<html>x</html>") == str(chosen)
    assert chosen.read_text(encoding="utf-8") == "<html>x</html>"

def test_api_save_cancelled_returns_none(tmp_path, sample_doc):
    api = Api(sample_doc, dialog=lambda d, name: None)
    assert api.save("<html>x</html>") is None

def test_api_prefs_round_trip(tmp_path, sample_doc, monkeypatch):
    monkeypatch.setattr(viewer, "settings_path", lambda: tmp_path / "s.json")
    api = Api(sample_doc, dialog=lambda d, n: None)
    assert api.set_prefs({"dark": True})["dark"] is True
    assert api.get_prefs()["dark"] is True
```

- [ ] **Step 2: Run** `pytest tests/test_viewer.py -v` → FAIL.

- [ ] **Step 3: Implement `viewer.py`.** Decisions:
  - `safe_filename`: replace each character in `<>:"/\|?*` and control characters with `_`, strip whitespace, empty → `document`, then append `-readable.html`.
  - Default dialog: `api.window.create_file_dialog(webview.SAVE_DIALOG, directory=str(documents_dir()), save_filename=name)`; pywebview returns a string, tuple or `None`; normalize to `Path | None`.
  - `documents_dir`: `Path.home() / "Documents"`.
  - `get_prefs`/`set_prefs` use `settings.load_prefs(settings_path())` and `save_prefs` via a module-level `settings_path` name so tests can patch it.

- [ ] **Step 4: Run** `pytest tests/test_viewer.py -v` → PASS.

- [ ] **Step 5: Commit** `feat: reading window with save and prefs bridge`.

---

### Task 9: Tray, orchestration, entry point, README

**Files:**
- Create: `pdf_helper/tray.py`, `pdf_helper/app.py`, `pdf_helper/__main__.py`, `ReadableDocument.pyw`, `scripts/thread_check.py`, `README.md`
- Modify: `pdf_helper/errors.py` (add `show_error`, `log_exception`)
- Test: `tests/test_tray.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `window_finder.Candidate/resolve_source/FileSource/CaptureSource`, `pdf.extract`, `ocr.extract/extract_file`, `capture.capture_window`, `viewer.open_document`, `errors.UserFacingError`.
- Produces:
  - `tray.SHELL_CLASSES: frozenset[str]` = `{"Shell_TrayWnd","Progman","WorkerW","Windows.UI.Core.CoreWindow","NotifyIconOverflowWindow"}`
  - `tray.accept_window(title: str, cls: str, pid: int, own_pid: int, visible: bool) -> bool`
  - `tray.ForegroundTracker(poll_seconds: float = 0.5)` with `start()`, `stop()`, property `candidate: Candidate | None`
  - `tray.make_icon_image() -> PIL.Image` (64×64, drawn with ImageDraw: rounded page with three text lines)
  - `tray.build_icon(on_read: Callable[[], None], on_quit: Callable[[], None]) -> pystray.Icon` (menu: "Read document" default item, "Quit")
  - `app.run_read_pass(candidate: Candidate | None) -> None`
  - `app.safe_read_pass(candidate: Candidate | None) -> None` (catches everything, shows message boxes, logs)
  - `errors.show_error(message: str, title: str = "Readable Document") -> None` (`MessageBoxW` with flags `0x30 | 0x40000`)
  - `errors.log_exception(exc: BaseException) -> None` (appends timestamp + traceback to `error.log`)
  - `__main__.main() -> None`

- [ ] **Step 1: Thread-ownership spike** (spec §4 risk). Write `scripts/thread_check.py`: create a hidden pywebview window (`webview.create_window("placeholder", html="<p>hidden</p>", hidden=True)`), call `webview.start(func=start_tray)` where `start_tray` builds a pystray icon whose only menu item calls `webview.create_window("Second", html="<h1>It works</h1>")` and runs `icon.run_detached()`. Run it. Expected: tray icon appears, clicking the item opens the second window, Quit stops the icon and `webview` exits once all windows close. If `run_detached` fails on this machine, switch the plan's `__main__` to the fallback in spec §4 (pystray on main thread, pywebview on its own thread) and note it in the README. Record the outcome in the commit message.

- [ ] **Step 2: Write failing tests** `tests/test_tray.py` and `tests/test_app.py`:

```python
# test_tray.py
def test_accept_window_rules():
    assert accept_window("report.pdf - Edge", "Chrome_WidgetWin_1", 10, 99, True)
    assert not accept_window("", "Chrome_WidgetWin_1", 10, 99, True)
    assert not accept_window("Start", "Windows.UI.Core.CoreWindow", 10, 99, True)
    assert not accept_window("Taskbar", "Shell_TrayWnd", 10, 99, True)
    assert not accept_window("Me", "X", 99, 99, True)
    assert not accept_window("Hidden", "X", 10, 99, False)

def test_icon_image_is_64px():
    assert make_icon_image().size == (64, 64)

# test_app.py
def test_run_read_pass_routes_pdf(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"; f.write_bytes(b"x")
    monkeypatch.setattr(app, "resolve_source", lambda c: FileSource(f))
    monkeypatch.setattr(app, "extract_pdf", lambda p: "DOC")
    opened = []; monkeypatch.setattr(app, "open_document", opened.append)
    run_read_pass(Candidate(1, "t", 2, "c"))
    assert opened == ["DOC"]

def test_run_read_pass_routes_capture_with_label(monkeypatch):
    monkeypatch.setattr(app, "resolve_source", lambda c: CaptureSource(7, "Some Page"))
    monkeypatch.setattr(app, "capture_window", lambda h: ("IMG", "screen"))
    calls = []; monkeypatch.setattr(app, "extract_ocr", lambda img, title, label: calls.append((img, title, label)) or "DOC")
    monkeypatch.setattr(app, "open_document", lambda d: None)
    run_read_pass(Candidate(7, "Some Page", 2, "c"))
    assert calls == [("IMG", "Some Page", "captured from window: Some Page (screen region capture)")]

def test_safe_read_pass_shows_user_facing_error(monkeypatch):
    shown = []; monkeypatch.setattr(app, "show_error", lambda m, title="": shown.append(m))
    monkeypatch.setattr(app, "run_read_pass", lambda c: (_ for _ in ()).throw(UserFacingError("Nope")))
    safe_read_pass(None)
    assert shown == ["Nope"]

def test_safe_read_pass_logs_unexpected_error(monkeypatch):
    shown = []; logged = []
    monkeypatch.setattr(app, "show_error", lambda m, title="": shown.append(m))
    monkeypatch.setattr(app, "log_exception", logged.append)
    monkeypatch.setattr(app, "run_read_pass", lambda c: 1 / 0)
    safe_read_pass(None)
    assert shown[0].startswith("Something went wrong: ZeroDivisionError") and len(logged) == 1
```

- [ ] **Step 3: Run** `pytest tests/test_tray.py tests/test_app.py -v` → FAIL.

- [ ] **Step 4: Implement `errors.py` additions, `tray.py`, `app.py`, `__main__.py`, `ReadableDocument.pyw`.** Decisions:
  - `app.py` imports the collaborators under the names the tests patch: `from .window_finder import resolve_source`, `from .extract.pdf import extract as extract_pdf`, `from .extract.ocr import extract as extract_ocr, extract_file as extract_image`, `from .capture import capture_window`, `from .viewer import open_document`, `from .errors import show_error, log_exception`. Import `extract_ocr`/`extract_image` lazily inside functions is NOT allowed here (tests patch module attributes), so `ocr.py` must keep winrt imports lazy (Task 5 does).
  - Capture label: `f"captured from window: {title}"` plus ` (screen region capture)` when the method is `"screen"`.
  - `ForegroundTracker` thread is a daemon; it reads `win32gui.GetForegroundWindow`, `GetWindowText`, `GetClassName`, `IsWindowVisible`, `win32process.GetWindowThreadProcessId(hwnd)[1]`, and stores the candidate under a lock.
  - `__main__.main`: `webview.create_window("Readable Document", html="<p></p>", hidden=True)`; `webview.start(func=_start_tray)`. `_start_tray` starts the tracker, builds the icon with `on_read=lambda: threading.Thread(target=safe_read_pass, args=(tracker.candidate,), daemon=True).start()` and `on_quit` that stops the icon, then destroys every window in `webview.windows`; `icon.run_detached()`. If the spike in Step 1 chose the fallback, implement that instead.
  - `ReadableDocument.pyw`: `from pdf_helper.__main__ import main; main()` with `sys.path` set to its own folder.

- [ ] **Step 5: Run** `pytest -v` (whole suite) → all PASS.

- [ ] **Step 6: Write `README.md`**: what it does, install (`py -3.14 -m pip install -r requirements.txt`), run (`ReadableDocument.pyw`, how to make a Start-up shortcut), how source detection works and the privacy guarantee (only the window is captured, nothing stored), the OCR language-pack note, and the manual smoke checklist from spec §6.

- [ ] **Step 7: Manual smoke test** (spec §6), each line checked off in the commit message: tray appears; PDF in Edge → file found; PDF in SumatraPDF or Acrobat → file via command line; PNG in Photos → OCR; web page in a browser → window capture + OCR with the "captured from window" header; Save → file opens in a browser with the same look and Save hidden; change Dark + size, close, read again → persisted; no document window → message box; tray still alive after each error.

- [ ] **Step 8: Commit** `feat: tray app, orchestration and launcher`.

---

## Self-review notes

- Spec coverage: §5.1 → Task 9 (`accept_window`, tracker); §5.2 → Task 6; §5.3 → Task 7; §5.4 → Task 2; §5.5 → Task 4; §5.6 → Tasks 2 and 5; §5.7 → Task 3; §5.8 → Task 8; §5.9 → Task 1; §5.10 → Task 9; §6 tests mapped per task; §7 risks → Task 9 Step 1 (threads), Task 7 fallback (black PrintWindow), Task 5 (language pack).
- Type consistency: `Candidate` lives in `window_finder` and is imported by `tray` and `app`; `Line` lives in `layout` and is used by `pdf` and `ocr`; `extract_ocr(img, title, label)` matches `ocr.extract(image, title, source_label)`.
- Review Focus items each have a pinned test: 1 → Task 4 blank page; 2 → Task 6 title parametrize; 3 → Task 1 wrong types; 4 → Task 2 empty/single, Task 5 too-little/single-line; 5 → Task 8 `safe_filename`.
