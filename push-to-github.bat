@echo off
chcp 65001 >nul
REM ============================================================================
REM  20SecondsOfSilence - 一键推送到 GitHub（国内网络/镜像版）
REM
REM  本机直连 github.com:443 不通，但通过镜像可以访问仓库，所以这里走镜像。
REM  双击运行，首次会弹窗要求登录 GitHub（浏览器授权），登录一次即可。
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
echo  推送 20SecondsOfSilence 到 github.com/MOBie2604/20SecondsOfSilence
echo  通过镜像加速（本机直连 GitHub 不通）
echo ============================================================
echo.

echo [1/3] 列出可用的镜像，测试连通性 ...
set "MIRROR="
for %%M in (
    https://ghfast.top/https://github.com/MOBie2604/20SecondsOfSilence.git
    https://ghproxy.net/https://github.com/MOBie2604/20SecondsOfSilence.git
    https://gh-proxy.com/https://github.com/MOBie2604/20SecondsOfSilence.git
) do (
    if not defined MIRROR (
        "%GIT%" ls-remote %%M HEAD >nul 2>&1
        if not errorlevel 1 (
            echo       可用: %%M
            set "MIRROR=%%M"
        )
    )
)
if not defined MIRROR (
    echo.
    echo [失败] 所有镜像都连不上。
    echo   请检查网络，或开启代理后再试。
    echo   如果开了代理，先执行下面两行把 git 走代理：
    echo     git config --global http.proxy http://127.0.0.1:端口
    echo     git config --global https.proxy http://127.0.0.1:端口
    pause
    exit /b 1
)

"%GIT%" remote set-url origin "%MIRROR%"

echo.
echo [2/3] 推送本地提交 ...
echo       （如果弹出登录窗口，选 "Sign in with your browser" 用浏览器授权）
echo.
"%GIT%" push origin main
if errorlevel 1 (
    echo.
    echo [失败] 推送未完成，常见原因：
    echo   - 账号或密码 / Token 错误（GitHub 已不支持密码，需要 Personal Access Token）
    echo   - 没有该仓库的写权限
    echo   - 镜像临时故障，重新双击本脚本再试
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  推送成功！
echo  仓库地址: https://github.com/MOBie2604/20SecondsOfSilence
echo.
echo  下一步（可选）：去 Releases 页面发布 v1.0.0，
echo  把 20SecondsOfSilence-win64.zip 作为附件上传，别人就能直接下载免安装版。
echo  注意：推送用的是镜像地址，网页上看到的仍然是 GitHub 原址，不影响使用。
echo ============================================================
pause
endlocal
