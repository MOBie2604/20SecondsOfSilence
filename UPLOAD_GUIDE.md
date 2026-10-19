# 上传到 GitHub —— 照做就行

本地仓库已经初始化好并提交了第一次 commit（16 个文件，2822 行），分支是 `main`。
下面从"建仓库"到"发 Release"一步步来。

---

## 第 0 步：改掉占位符（重要）

仓库里还有 3 处占位符，上传前先替换：

| 文件 | 行 | 内容 |
| --- | --- | --- |
| `README.md` | 92 | `git clone https://github.com/MOBie2604/20SecondsOfSilence.git` |
| `README.md` | 末尾 | `[MIT](LICENSE) © 2026 MOBie2604` |
| `LICENSE` | 3 | `Copyright (c) 2026 MOBie2604` |
| `.github/ISSUE_TEMPLATE/config.yml` | 4 | 常见问题链接里的 `MOBie2604` |

用 PowerShell 一把替换（把 `MOBie2604` 换成实际 GitHub 用户名）：

```powershell
cd 20SecondsOfSilence
$u = "MOBie2604"
(Get-Content README.md -Raw -Encoding utf8) -replace 'MOBie2604', $u | Set-Content README.md -Encoding utf8 -NoNewline
(Get-Content LICENSE -Raw -Encoding utf8)  -replace 'MOBie2604', $u | Set-Content LICENSE  -Encoding utf8 -NoNewline
(Get-Content .github\ISSUE_TEMPLATE\config.yml -Raw -Encoding utf8) -replace 'MOBie2604', $u | Set-Content .github\ISSUE_TEMPLATE\config.yml -Encoding utf8 -NoNewline

# 顺便设置 git 身份（之前是占位符）
git config user.name  "MOBie2604"
git config user.email "你的邮箱"
git add -A
git commit -m "docs: 填入仓库地址和作者信息"
```

---

## 第 1 步：在 GitHub 上建空仓库

1. 打开 <https://github.com/new>
2. **Repository name** 填 `20SecondsOfSilence`
3. **Description** 复制这句：

   ```text
   纯 Python 标准库写的强制休息护眼提醒 · 零依赖、完全离线、能挡住游戏的 Alt+Tab
   ```

4. 选择 **Public**
5. ⚠️ **不要勾选** "Add a README file"、".gitignore"、"license"（本地已经有了，勾了会冲突）
6. 点 **Create repository**

---

## 第 2 步：推送

GitHub 建好后会显示一串命令，用下面这段（换成MOBie2604）：

```powershell
cd 20SecondsOfSilence
git remote add origin https://github.com/MOBie2604/20SecondsOfSilence.git
git push -u origin main
```

如果提示要登录：直接走浏览器授权即可（Git for Windows 自带 Credential Manager 会弹窗）。

> 备注：这台机器上 `git` 没加进 PATH，如果命令行找不到，用全路径
> `"C:\Program Files\Git\cmd\git.exe"` 代替开头的 `git` 就行。

---

## 第 3 步：发 Release（exe 放这里）

`dist/` 故意没进仓库，exe 通过 Release 分发。zip 已经打包好在：

```
C:\Users\26940\Documents\deepseek-harness\default-workspace\20SecondsOfSilence-release\20SecondsOfSilence-win64.zip
```

操作：

1. 仓库页面右侧 **Releases** → **Create a new release**
2. **Choose a tag** 输入 `v1.0.0`，点 "Create new tag: v1.0.0 on publish"
3. **Release title**：`20SecondsOfSilence v1.0.0 — 第一次发布`
4. **Description**：把项目里 `RELEASE_NOTES.md` 的正文（从 `## 20SecondsOfSilence v1.0.0` 开始）整段粘进去
5. **Attach binaries**：把 `20SecondsOfSilence-win64.zip` 拖进那个虚线框
6. 点 **Publish release**

## 第 4 步：给仓库加 Topics（提高被发现率）

仓库首页右侧齿轮图标 ⚙️ → Topics，填入：

```text
eye-care  pomodoro  tkinter  python  windows  productivity  health  offline  no-dependencies  break-reminder
```

## 第 5 步（可选）：加个演示图

README 里现在只有图标 `assets/20SecondsOfSilence.png`。如果想让项目页更好看，可以把
浮窗、预警态、全屏提醒三张截图放进 `assets/` 并在 README 里引用。

---

## 检查清单

上传前对照一下：

- [ ] 3 处 `MOBie2604` 都替换了
- [ ] `git status` 干净，没有 `dist/`、`build/`、`20SecondsOfSilence.log`
- [ ] `python _smoke_test.py` 输出 `ALL OK`
- [ ] GitHub 建仓库时**没有**勾选 README / gitignore / license
- [ ] Release 里传的是 `20SecondsOfSilence-win64.zip`（不是单独的 exe）
- [ ] Release 说明里提醒了"要整个文件夹，不能只拿 exe"

---

## 仓库里到底有什么

```
20SecondsOfSilence/
├── main.py                           程序本体（1827 行，单文件）
├── config.json                       默认配置（43 个键）
├── README.md                         项目主页文档
├── RELEASE_NOTES.md                  发布说明模板（粘到 Release 用）
├── LICENSE                           MIT
├── requirements.txt                  依赖清单（结论：无）
├── build.bat                         一键打包成 exe（纯 ASCII，跑得通）
├── _smoke_test.py                    自检脚本，跑完输出 ALL OK
├── .gitignore                        排除 dist/ build/ *.log
├── .gitattributes                    统一换行符
├── assets/
│   ├── 20SecondsOfSilence.ico / .png           图标
└── .github/
    ├── ISSUE_TEMPLATE/               Bug / 功能建议模板 + 联系链接
    └── PULL_REQUEST_TEMPLATE.md      PR 模板（含"不许加依赖/联网"检查项）
```

刻意**没有**放进仓库的：`dist/`（26 MB 二进制）、`build/`、`*.spec`、`20SecondsOfSilence.log`、
`__pycache__/`。这些都在 `.gitignore` 里。
