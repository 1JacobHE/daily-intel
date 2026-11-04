@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   GitHub 涨星雷达 + A股要闻 · 一键更新
echo ============================================
echo.
echo 说明：已启用每日自动更新（每天 08:30）。
echo       本脚本用于手动补跑，随时双击即可。
echo.
echo 将依次执行：抓 GitHub -^> 抓快讯+五轴评分 -^> 合并要闻
echo               -^> 归档 -^> 事件聚簇 -^> 时间线 -^> 周报 -^> 导出
echo.

set PYEXE=python
if exist "C:\Users\73410\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
  set PYEXE=C:\Users\73410\.workbuddy\binaries\python\versions\3.13.12\python.exe
)

"%PYEXE%" daily_update.py
if errorlevel 1 (
  echo.
  echo [警告] 部分环节失败，已保留上一次数据文件。
  echo        详情见上方输出。按任意键退出。
  pause >nul
  exit /b 1
)

echo.
echo [最后一步] 正在打开看板 ...
start "" "index.html"

echo.
echo 完成。数据已更新到 data/ 目录。
echo 提示：重跑本脚本是幂等的，同一天多次运行不会造成数据重复。
timeout /t 4 >nul
