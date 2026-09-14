@echo off
cd /d D:\scalperagent_v4
node apply_edits.mjs
if errorlevel 1 exit /b 1
del EXECUTE.txt cleanup_list.txt run_steps.txt apply_edits_package.json apply_edits.cmd apply_edits.mjs
echo CLEANUP DONE
