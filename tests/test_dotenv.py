from pdf_helper.dotenv import load_dotenv, parse_dotenv


def test_parse_dotenv_handles_quotes_comments_and_blank_lines():
    text = """
# the key
ANTHROPIC_API_KEY = "sk-ant-abc123"
OTHER='single quoted'
export EXPORTED=value with spaces
BROKEN LINE WITHOUT EQUALS
EMPTY=
"""
    assert parse_dotenv(text) == {
        "ANTHROPIC_API_KEY": "sk-ant-abc123",
        "OTHER": "single quoted",
        "EXPORTED": "value with spaces",
        "EMPTY": "",
    }


def test_load_dotenv_sets_missing_vars_only(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-file\nPDF_HELPER_X=new\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-environment")
    monkeypatch.delenv("PDF_HELPER_X", raising=False)
    loaded = load_dotenv(env_file)
    assert loaded == {"PDF_HELPER_X"}
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "from-environment"
    assert os.environ["PDF_HELPER_X"] == "new"


def test_load_dotenv_missing_file_is_fine(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == set()
