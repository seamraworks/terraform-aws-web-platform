"""Build the deterministic, dependency-free Lambda archive before Terraform."""
from pathlib import Path
import zipfile

directory = Path(__file__).resolve().parent
with zipfile.ZipFile(directory / "alert-mail.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    item = zipfile.ZipInfo("handler.py", (2026, 1, 1, 0, 0, 0))
    item.compress_type = zipfile.ZIP_DEFLATED
    item.external_attr = 0o644 << 16
    archive.writestr(item, (directory / "handler.py").read_text(encoding="utf-8").replace("\r\n", "\n"))
print("Built alert-mail.zip")
