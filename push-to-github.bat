@echo off
chcp 65001 >nul
REM ============================================================================
REM  EyeGuard - 一键推送到 GitHub
REM  双击运行即可。首次推送会弹窗要求登录 GitHub（浏览器授权），登录一次就行。
REM ============================================================================

setlocal
cd /d "%~dp0"

set "GIT=git"
where git >nul 2>&1
if errorlevel 1 (
    if exist "C:\Program Files\Git\cmd\git.exe" (
        set "GIT=C:\Program Files\Git\cmd\git.exe"
    ) else (
        echo [错误] 没找到 git，请先安装 Git: https://git-scm.com/download/win
        pause
        exit /b 1
    )
)

echo.
echo ============================================================
echo  推送到 https://github.com/MOBie2604/EyeGuard-
echo ============================================================
echo.

"%GIT%" remote -v
echo.
echo [1/2] 测试网络连通性 ...
"%GIT%" ls-remote origin HEAD >nul 2>&1
if errorlevel 1 (
    echo.
    echo [失败] 连不上 github.com。
    echo.
    echo   可能原因：
    echo     1. 网络无法访问 GitHub（国内常见，需要代理/VPN/加速器）
    echo     2. 有代理但 git 没配置，试试下面命令后再运行本脚本：
    echo        git config --global http.proxy http://127.0.0.1:你的端口
    echo        git config --global https.proxy http://127.0.0.1:你的端口
    echo.
    pause
    exit /b 1
)
echo       网络正常。

echo [2/2] 推送 ...
"%GIT%" push -u origin main
if errorlevel 1 (
    echo.
    echo [失败] 推送未完成。
    echo   认证失败的话，Windows 会弹出登录窗口，选 "Sign in with your browser"
    echo   用浏览器授权 GitHub 账号即可，登录成功后会自动继续推送。
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  推送成功！打开 https://github.com/MOBie2604/EyeGuard- 看看
echo.
echo  别忘了再去 Releases 页面新建一个 v1.0.0 发布，
echo  把 EyeGuard-win64.zip 作为附件上传（免费版安装包不放仓库）。
echo ============================================================
pause
endlocal
