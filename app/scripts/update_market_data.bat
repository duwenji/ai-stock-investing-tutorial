@echo off
cd /d %~dp0..
uv run python -m scripts.update_market_data
exit /b %errorlevel%
