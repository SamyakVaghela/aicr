from aicr.chunker import FileDiff, pack, split_diff, truncate_file_diff

DIFF = """\
diff --git a/app/main.py b/app/main.py
index 111..222 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,3 +1,4 @@
 import os
+API_KEY = "sk-live-abcdefghijklmno"

 def run():
diff --git a/web/app.js b/web/app.js
index 333..444 100644
--- a/web/app.js
+++ b/web/app.js
@@ -10,2 +10,3 @@
 const x = 1;
+eval(userInput);
"""


def test_split_diff_finds_each_file():
    files = split_diff(DIFF)
    assert [f.path for f in files] == ["app/main.py", "web/app.js"]
    assert files[0].added_lines == 1
    assert not files[0].binary


def test_split_diff_empty():
    assert split_diff("") == []
    assert split_diff("   \n") == []


def test_binary_detection():
    d = ("diff --git a/logo.png b/logo.png\n"
         "index 1..2 100644\nBinary files a/logo.png and b/logo.png differ\n")
    files = split_diff(d)
    assert len(files) == 1 and files[0].binary


def test_pack_respects_budget():
    files = [FileDiff(path=f"f{i}.py", text="x" * 100) for i in range(10)]
    chunks = pack(files, chunk_bytes=250)
    assert len(chunks) == 5
    assert all(c.size <= 300 for c in chunks)
    assert sum(len(c.files) for c in chunks) == 10


def test_truncate_keeps_head_and_tail():
    fd = FileDiff(path="big.py", text="A" * 1000 + "Z" * 1000)
    out = truncate_file_diff(fd, 500)
    assert len(out.text) < 2000
    assert "omitted" in out.text


def test_chunk_render_has_file_headers():
    chunks = pack(split_diff(DIFF), chunk_bytes=100_000)
    body = chunks[0].render()
    assert "=== FILE: app/main.py ===" in body
    assert "=== FILE: web/app.js ===" in body
