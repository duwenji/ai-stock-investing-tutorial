@echo off
cd /d %~dp0..
uv run python -m scripts.import_all_listed_tickers
exit /b %errorlevel%
