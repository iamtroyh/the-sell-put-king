#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick Sync InvestSkill Reports to Dashboard
Synchronizes latest reports from InvestSkill/output and re-renders report.html.

InvestSkill GitHub: https://github.com/yennanliu/InvestSkill
"""
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_default_investskill = os.path.join(BASE_DIR, "InvestSkill") if os.path.exists(os.path.join(BASE_DIR, "InvestSkill")) else os.path.expanduser("~/InvestSkill")
INVESTSKILL_DIR = os.environ.get("INVESTSKILL_DIR", _default_investskill)

def main():
    print("=== Syncing InvestSkill Reports to Dashboard ===")
    
    # 1. Rebuild InvestSkill output/index.html
    index_script = os.path.join(INVESTSKILL_DIR, "scripts", "generate-output-index.js")
    if os.path.exists(index_script):
        subprocess.run(["node", index_script], check=False)
        print("Updated InvestSkill index: output/index.html")

    # 2. Re-render report.html dashboard
    gen_script = os.path.join(BASE_DIR, "scripts", "generate_report.py")
    res = subprocess.run(["python3", gen_script], capture_output=True, text=True)
    if res.returncode == 0:
        print("\n🎉 同步成功！您可直接在浏览器中刷新 report.html 查看最新研报！")
    else:
        print("❌ 生成 report.html 失败:")
        print(res.stderr)

if __name__ == "__main__":
    main()
