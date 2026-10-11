# Windows 源码运行与构建

只想使用应用，请到 [Releases](https://github.com/YeLn10/osu-paint/releases) 下载 `osu-paint-v版本-windows-x64.zip`，解压后运行 `osu-paint.exe`，无需安装 Python。

## 准备环境

构建目标为 Windows 10/11 x64。CI 使用 Windows Server 2022、Python **3.11.9 x64**；建议本地使用同一 Python 版本。源码支持 Python 3.10+，但其他版本未作为发布构建基准。

- 安装 [Git for Windows](https://git-scm.com/download/win)。
- 安装 [Python 3.11.9](https://www.python.org/downloads/release/python-3119/)，保留 Tcl/Tk 和 pip 组件。
- 完整测试还需 [Node.js 24](https://nodejs.org/)；只用于验证 HTML 预览，不是应用运行依赖。
- 首次安装依赖需要网络。FFmpeg 由 `imageio-ffmpeg` 提供，不必另装。

在 PowerShell 中克隆并进入项目：

```powershell
git clone https://github.com/YeLn10/osu-paint.git
cd osu-paint
py -3.11 -m venv .build-env
.\.build-env\Scripts\python.exe -m pip install -r requirements.txt
```

不必激活虚拟环境，后续命令显式使用其中的 Python，不受 PowerShell 激活脚本限制。

## 从源码启动

```powershell
.\.build-env\Scripts\python.exe osu_paint_desktop.py
```

可使用 `examples/heart.txt`、`examples/pulse.txt` 或 `examples/free.json` 测试；用 CLI 生成示例：

```powershell
.\.build-env\Scripts\python.exe osu_paint.py examples/heart.txt --start-ms 2000 --end-ms 4000 --fast-clear --output output/heart
```

文字编译和皮肤构建仅依赖 Python 标准库；音视频导入、播放按需使用固定版本的第三方依赖。

## 测试

```powershell
$env:PYTHONUTF8 = "1"
$env:SDL_AUDIODRIVER = "dummy"
node --version
.\.build-env\Scripts\python.exe -m unittest discover -s tests -v
```

`SDL_AUDIODRIVER=dummy` 让音频回归使用静音输出设备。测试仍实际解码合成音视频，并创建 Tk 窗口验证编辑行为。Node.js 不可用时部分 HTML 检查会跳过；发布前应安装它并运行完整测试。结束测试后可用 `Remove-Item Env:SDL_AUDIODRIVER` 恢复正常播放。

## 皮肤构建

修改皮肤时重建全部十个默认 24 行交付包，并确认回归；资源约束见 [皮肤说明](skin.md)：

```powershell
.\.build-env\Scripts\python.exe tools/build_skin.py
.\.build-env\Scripts\python.exe -m unittest discover -s tests -p test_skin.py -v
```

## 构建独立 EXE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_desktop.ps1
```

脚本自动复用 `.build-env`，安装固定版本的 PyInstaller 和 `requirements.txt`，将 FFmpeg 与音频组件打包到 `dist/osu-paint.exe`。如果尚无构建环境且 `python` 不在 PATH，可指定安装路径：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_desktop.ps1 -Python "C:\Python311\python.exe"
```

随后核验 EXE 内的根目录项目模块及 `osu_paint_app/` 下的全部 Python 模块与当前源码一致，并检查音视频组件：

```powershell
.\.build-env\Scripts\python.exe tools/verify_package.py
```

EXE、构建缓存和环境分别位于 `dist/`、`build/`、`.build-env/`，均被 Git 忽略。仅修改文档、皮肤或发布工具无需重建 EXE；修改应用源码后必须重建并核验。

`tools/verify_package.py` 从根目录 `osu_paint*.py` 和 `osu_paint_app/**/*.py` 收集模块，包括包初始化文件；新增文件无需维护固定模块清单。模块缺失或包内代码与源码不符都会令核验失败。模块职责和对应回归见 [架构的迭代入口](architecture.md#迭代入口)。

## 常见问题

| 问题 | 处理 |
| --- | --- |
| `No module named tkinter` | 用带 Tcl/Tk 的 Python Windows 安装器修复安装，再重建虚拟环境。 |
| 找不到 Python / pip | 显式指定 Python 路径，并用 `python.exe -m pip`。 |
| 构建无法覆盖 EXE | 关闭正在运行的 `osu-paint.exe`，保留或保存项目后重试。 |
| 构建后没有音乐 | 检查 `requirements.txt` 已完整安装；用 `tools/verify_package.py` 核验包内组件。 |
| 源码能启动，EXE 与行为不符 | 确认打开的是本次 `dist/osu-paint.exe`，不要继续使用旧副本。 |
| 下载的 EXE 被系统提示未知发布者 | 当前发布未做代码签名；从本仓库 Release 下载并比对 `SHA256SUMS.txt`，或自行从源码构建。 |

发布步骤见 [releasing.md](releasing.md)，实现边界见 [architecture.md](architecture.md)。
