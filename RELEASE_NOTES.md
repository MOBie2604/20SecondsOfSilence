# 发布说明模板 —— 复制到 GitHub Release 页面使用

## 20SecondsOfSilence v1.0.0 — 第一次发布

一个纯 Python 标准库写的护眼强制休息提醒，零第三方依赖，完全离线。

### 下载

| 文件 | 说明 |
| --- | --- |
| `20SecondsOfSilence-win64.zip` | **Windows 免安装版**，解压后双击 `20SecondsOfSilence.exe` 即可，**不需要装 Python** |
| 源码 (`Source code`) | 任意平台，`python main.py` 运行 |

> 解压后请保持 `20SecondsOfSilence.exe` 和 `_internal\` 文件夹在同一目录，**不要只拿出单个 exe**。

### 这个版本有什么

- **常驻半透明浮窗**：置顶显示 `mm:ss` 倒计时，可拖动，右键打开菜单
- **定时全屏提醒**：环形倒计时，25 秒后自动消失并重置计时
  - 屏蔽关闭按钮 / `Esc` / `Alt+F4`
  - Windows 上额外屏蔽 `Alt+Tab` / `Win` 键 / `Ctrl+Esc`（低级键盘钩子）
  - 周期性重新置顶 + 抢焦点，防止被游戏盖住
- **提前预警**：提醒前 30 秒、5 秒时浮窗变色闪烁，不打断操作
- **配置热重载**：改 `config.json` 保存后 1 秒内自动生效，不用重启

### 系统要求

- Windows 10 / 11（主要支持）
- macOS / Linux 可运行，但**屏蔽快捷键和抢焦点不可用**（系统限制），会自动降级

### 安全性

- **100% 本地运行，不联网、不收集、不上传任何数据**
- 源码只有 1800 行左右明文 Python，可逐行审计
- 所有"敏感行为"（抢焦点、屏蔽快捷键、隐藏鼠标等）都可在 `config.json` 里单独关闭，见 README

### 已知限制

- `Ctrl+Alt+Del` 是内核级组合键，任何用户态程序都**拦不住**（包括本程序）
- 多显示器时全屏提醒默认只覆盖主屏
- 独占全屏的游戏可能仍会盖住提醒，建议用「无边框窗口」模式

---

## 安装步骤（给第一次用的人）

1. 下载 `20SecondsOfSilence-win64.zip` 并解压到任意目录（**路径含中文和空格也没问题**）
2. 双击 `20SecondsOfSilence.exe`
3. 屏幕左上角出现倒计时小浮窗，说明正常运行
4. 想改间隔：右键浮窗 →「打开配置文件夹」→ 改 `config.json` 里的 `interval_minutes`
5. 想关掉：右键浮窗 →「退出 20SecondsOfSilence」

第一次运行会在 exe 旁边自动生成 `config.json` 和 `20SecondsOfSilence.log`。
