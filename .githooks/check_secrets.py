"""commit 前檢查：擋下 API key、.env、資料庫被加進 Git。

由 .githooks/pre-commit 自動執行；也可以手動檢查整個專案：
    python .githooks/check_secrets.py --all
"""
import re
import subprocess
import sys
from pathlib import PurePosixPath

# 不能進 Git 的檔案
BLOCKED_FILES = [
    (re.compile(r"(^|/)\.env(\..+)?$"), ".env 金鑰檔"),
    (re.compile(r"\.db(-journal)?$"), "資料庫（含家人紀錄）"),
]
ALLOWED_FILES = {".env.example"}

# 內容裡不能出現的金鑰
SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "Google / Gemini API key"),
    (re.compile(r"\bAQ\.[0-9A-Za-z_\-.]{30,}"), "Google / Gemini API key（新格式）"),
    # 金鑰變數被直接寫了值（.env.example 留空不會觸發）
    (re.compile(r"(GEMINI_API_KEY|GOOGLE_API_KEY|LINE_CHANNEL_SECRET|LINE_CHANNEL_ACCESS_TOKEN)"
                r"\s*[:=]\s*['\"]?[A-Za-z0-9+/=_\-.]{16,}"), "金鑰變數有填值"),
    # LINE channel access token 是一長串 base64（約 170 字）
    (re.compile(r"[A-Za-z0-9+/]{120,}={0,2}"), "疑似 LINE access token（超長 base64）"),
]


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def files_to_check(check_all: bool) -> list[str]:
    if check_all:
        out = git("ls-files", "--cached", "--others", "--exclude-standard")
    else:
        out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [f for f in out.decode("utf-8").splitlines() if f]


def read(path: str, check_all: bool) -> bytes:
    if check_all:
        with open(path, "rb") as f:
            return f.read()
    return git("show", f":{path}")  # 檢查「已暫存」的版本，而不是工作目錄


def main() -> int:
    check_all = "--all" in sys.argv
    problems = []
    for path in files_to_check(check_all):
        name = PurePosixPath(path).name
        if name not in ALLOWED_FILES:
            for pattern, label in BLOCKED_FILES:
                if pattern.search(path):
                    problems.append(f"{path}：{label}不應該上傳")
        try:
            data = read(path, check_all)
        except (OSError, subprocess.CalledProcessError):
            continue
        if b"\0" in data[:8000]:  # 二進位檔
            continue
        text = data.decode("utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(line):
                    problems.append(f"{path}:{lineno}：{label}")

    if problems:
        print("🚫 發現可能外洩的金鑰或私人資料，已阻止 commit：", file=sys.stderr)
        for p in problems:
            print("   " + p, file=sys.stderr)
        print("\n金鑰請放在 .env（已被 .gitignore 排除）。"
              "\n已暫存的檔案可用 git restore --staged <檔案> 取消。", file=sys.stderr)
        return 1
    print("✅ 金鑰檢查通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
