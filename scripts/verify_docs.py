from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[2]
manifest = json.loads((root / "code-manifest.json").read_text())
for entry in manifest:
    source = root / "reference" / entry["path"]
    raw = source.read_text()
    assert hashlib.sha256(raw.encode()).hexdigest() == entry["sha256"], entry["path"]
    chapter = (root / entry["chapter"]).read_text()
    assert raw.rstrip() in chapter, "文档代码不同于源文件：" + entry["path"]
print("所有登记代码均在文档中完整展示，且与参考实现一致：", len(manifest), "个文件")
