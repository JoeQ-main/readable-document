# Readable Document

A small Windows tray utility. Click **Read document** in its tray menu and it
finds the PDF or text-heavy image you most recently had in front, sends it to
the Claude API, and opens a restyled version that is easier to focus on and
skim: short lines, generous spacing, clear headings with an outline, bolded
lead-ins, highlighted numbers. Nothing is written to disk unless you press
**Save**, which writes a standalone HTML file.

Claude transcribes the document and marks up its structure (headings,
paragraphs, lists). It is instructed never to reword, summarize or omit the
document's text. Only the presentation changes.

## Install

Python 3.14 on Windows 10 or 11, and a Claude API key.

```bash
py -3.14 -m pip install -r requirements.txt
```

Set the key as a user environment variable named `ANTHROPIC_API_KEY`
(*Settings → System → About → Advanced system settings → Environment
Variables*), then launch the app. Without a valid key every read fails with a
message saying so; there is no local fallback.

## Run

Double-click `ReadableDocument.pyw` (or make a shortcut to it; put the shortcut
in `shell:startup` to launch it at sign-in). A page icon appears in the tray.

1. View a PDF or image in any application.
2. Click the tray icon, then **Read document** (a single left-click on the icon
   does the same). A notification confirms the read has started; extra clicks
   while it runs are ignored.
3. A window titled *Readable: name* opens when Claude is done, usually within
   a minute, longer for long PDFs. Toolbar buttons change text size, line
   spacing, column width, dark mode, number highlighting and "bionic" bolding.
   Your choices are remembered for the next document.
4. **Save** writes the current view as `name-readable.html` to a location you
   pick. The saved file opens in any browser with the same look and toggles.
5. Close the window to discard it. You can open several at once. **Quit** in
   the tray menu exits.

## What is sent to Claude, and what it costs

- A PDF file is sent whole as a document (the API accepts up to 600 pages and
  30 MB), so Claude works from the real text and page images. Scanned PDFs
  work the same way.
- An image file, or a capture of the window in front, is sent as one image,
  scaled to at most 1568 px on its long side.
- The model is Claude Opus 5.5. A one-page capture costs a fraction of a cent;
  a 100-page PDF is roughly a dollar or two, mostly for the transcribed output.
  Server-side refusal fallback is enabled, so a safety decline on one model is
  retried on another inside the same request.

## How it finds the document, and what it captures

The app remembers the last window you had in front that is not the taskbar,
desktop, Start menu or a shell flyout, and is big enough to read. When you
click **Read document** it tries, in order:

1. The window's process command line names a PDF or image file (SumatraPDF,
   Acrobat, Photos, Paint and similar), and the window title does not name a
   different file. The file is read directly.
2. The window title contains a filename such as `report.pdf`. The file is
   looked up in Windows Recent Items, then in Downloads, Desktop and
   Documents (two folders deep); the newest match wins.
3. The title has no filename but looks like a browser tab (Firefox, Chrome and
   Edge show a PDF's own metadata title instead of its filename). The browser
   suffix is stripped and the same folders are searched for a PDF whose
   metadata title matches; the newest one wins.
4. Otherwise the window itself is captured with the Windows `PrintWindow`
   call, which renders only that window's own contents, and the capture is
   sent to Claude. Nothing else on screen is captured and the image is never
   saved. If `PrintWindow` yields nothing (some GPU-rendered windows), the
   window is brought to the front and its rectangle is grabbed from the
   screen; the header line then says *screen region capture*.
5. A PDF opened straight from the web exists only in the browser's cache.
   After the capture is transcribed, its lines are compared with the PDFs in
   Firefox's local cache; if one contains them, that whole cached document is
   read instead of just the visible page. This is a local file read.

The header line at the top of every reading window states which of these
happened, and flags text read from an image as possibly containing errors.

Supported files: `.pdf .png .jpg .jpeg .bmp .tif .tiff .webp .gif`.

The reading window loads its page from memory over a loopback-only HTTP
server inside the app (random port, unguessable token per document, page
forgotten when its window closes). Preferences live in
`%APPDATA%\PDFHelper\settings.json`; unexpected errors are logged to
`%APPDATA%\PDFHelper\error.log`.

## Development

```bash
py -3.14 -m pip install -r requirements-dev.txt
python -m pytest
```

Tests never call the API; `scripts/claude_check.py` sends the two fixtures in
`tests/fixtures` through the real API and prints the blocks it gets back
(needs `ANTHROPIC_API_KEY`). `scripts/thread_check.py` verifies the pywebview +
pystray threading setup; `scripts/capture_check.py` captures whichever window
you click within three seconds and shows the result.

### Manual smoke checklist

- Tray icon appears after launching `ReadableDocument.pyw`.
- PDF open in Edge → file found by title, whole document shown.
- PDF open in SumatraPDF or Acrobat → file found via command line.
- PNG open in Photos → transcribed, with the "read from an image" note.
- A web page in a browser → window capture, header says "captured from
  window".
- Save → file opens in a browser with the same look; Save button hidden there.
- Change Dark and text size, close, read again → settings persisted.
- No document window (fresh sign-in, nothing opened) → message box.
- No API key → message box naming `ANTHROPIC_API_KEY`; the tray survives.
