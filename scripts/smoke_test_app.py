"""Headless smoke test of the Streamlit app against the real workspace data.

Drives app/app.py with Streamlit's AppTest: loads Browse, applies filters, runs each search
mode and asks one example question, failing on any exception or error shown in the app.
Uses your Databricks CLI login, so it is not part of CI. It caught a pandas 3 bug the unit
tests missed; to try another pandas version: uv run --with pandas==3.1.1 python <this file>

Usage: uv run python scripts/smoke_test_app.py
"""

import sys
from pathlib import Path

import pandas
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
print("pandas", pandas.__version__)


def check(at, step):
    errors = [e.value for e in at.exception]
    print(f"{step}: {'OK' if not errors else 'ERROR ' + str(errors)[:500]}")
    if errors:
        sys.exit(1)


at = AppTest.from_file(APP, default_timeout=120).run()
check(at, "load")
print("  caption:", next(c.value for c in at.caption if c.value.startswith("Showing")))

# Browse filters: name, opinion type, author
at.text_input[0].set_value("State").run()
at.multiselect[0].set_value(["dissent"]).run()
at.multiselect[1].set_value(["Rush"]).run()
check(at, "browse filters")
print("  caption:", next(c.value for c in at.caption if c.value.startswith("Showing")))

# Search: each mode
for mode, query in [
    ("Exact words", "ineffective assistance"),
    ("People", "Rush"),
    ("Meaning", "police searched a car without a warrant"),
]:
    at.radio[0].set_value(mode).run()
    box = next(t for t in at.text_input if t.label == "Search")
    box.set_value(query).run()
    check(at, f"search {mode}")

# Ask: one example question
at.button(key="ex-3").click().run()
check(at, "ask")
errors = [e.value for e in at.error]
answers = [m for m in at.chat_message if m.name == "assistant" and m.markdown]
if errors or not answers:
    print("ask failed:", errors)
    sys.exit(1)
print("  answer:", answers[0].markdown[0].value[:200])
print("all OK")
