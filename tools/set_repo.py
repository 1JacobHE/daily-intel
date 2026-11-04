# -*- coding: utf-8 -*-
"""
set_repo.py — 把 index.html 里的数据源占位符替换成真实仓库

用法：python tools/set_repo.py <owner> <repo>
说明：重复执行安全（已替换过会原地更新，不会叠加）
"""
import re
import sys
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(HERE, "index.html")


def main():
    if len(sys.argv) < 3:
        print("用法: python tools/set_repo.py <owner> <repo>")
        return 1
    owner, repo = sys.argv[1].strip(), sys.argv[2].strip()

    with open(HTML, encoding="utf-8") as f:
        s = f.read()

    s = re.sub(r'const GH_OWNER = "[^"]*";', f'const GH_OWNER = "{owner}";', s)
    s = re.sub(r'const GH_REPO  = "[^"]*";', f'const GH_REPO  = "{repo}";', s)

    with open(HTML, "w", encoding="utf-8") as f:
        f.write(s)

    print(f"已写入数据源：{owner}/{repo}")
    print(f"  CDN   : https://cdn.jsdelivr.net/gh/{owner}/{repo}@main/")
    print(f"  Pages : https://{owner}.github.io/{repo}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
