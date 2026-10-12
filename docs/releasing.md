# 维护者发布指南

GitHub Actions 在推送 `main`、提交 Pull Request 或手动触发时运行 Windows 和 Linux 完整测试、构建与包内核验；非标签运行只生成 Actions 构建产物。推送形如 `v0.1.1` 的标签时，`Windows build` 还会调用同一提交的 `Linux build`，两平台均成功后打包并发布 GitHub Release。

`Linux build` 在分支、PR、手动运行和被标签流程调用时执行 Linux 完整测试、构建、核验和启动检查，生成 `linux-x64` Actions 产物，保留 14 天。标签运行中的 Linux 试用包同时上传到 Release，公开下载无需登录。运行要求见[构建指南](building.md#linux-x64)。

## 发布前

1. 更新 `CHANGELOG.md`，新增版本对应的 `docs/releases/v版本.md`。列出功能、升级方式和已知限制。
2. 按 [构建教程](building.md) 完成测试、皮肤检查（如有改动）、EXE 构建和包内核验。
3. 核对 `git status --short`，提交代码和文档。环境、凭据、个人项目和媒体均不要加入 Git。
4. 推送 `main`，等待 Windows 和 Linux CI 通过。

## 标签发布

以 v0.1.1 为例：

```powershell
git switch main
git pull --ff-only
git tag -a v0.1.1 -m "osu-paint v0.1.1"
git push origin main
git push origin v0.1.1
```

版本号须为 `v主版本.次版本.修订号`。不要移动已公开的版本标签；修复后发布新版本。

在仓库 [Actions](https://github.com/YeLn10/osu-paint/actions) 查看标签对应的 `Windows build`，其中包含被调用的 Linux 构建。发布 job 等待两平台通过，再下载同一次运行的产物、补充 Linux 校验值并发布；使用 GitHub 自动提供的 `GITHUB_TOKEN`，无需在仓库中保存个人 Token。发布 job 仅对标签开放 `contents: write`，构建 job 只读。

## Release 产物

| 文件 | 用途 |
| --- | --- |
| `osu-paint-v版本-windows-x64.zip` | EXE、README、使用指南、皮肤说明、界面图、更新日志、本版说明、示例与全部许可证。 |
| `osu-paint-v版本-linux-x64.tar.gz` | Linux x64 试用程序、README、使用指南、皮肤说明、界面图、更新日志、示例与全部许可证；保留可执行权限。 |
| `pixel-film-v版本-skins.zip` | lazer / stable 各五套皮肤，默认 24 行；实际作品优先使用应用导出的匹配行数皮肤。 |
| `osu-paint-v版本-source.zip` | 此版本的 Git 源码快照，包含构建脚本和文档。 |
| `SHA256SUMS.txt` | 下载文件的 SHA-256 校验值。 |
| `build-info.json` | 标签、提交、Python / 依赖版本和 EXE 校验值。 |
| `verify-linux-x64.json` | 同一标签运行中 Linux 包的模块一致性、媒体组件和程序校验值。 |

两个桌面包只包含使用材料，完整开发文档和研究记录放在源码包。打包时，已附带文件之间的 Markdown 链接按包内位置修正；其余链接指向本次提交的 GitHub 文件并保留锚点，避免皮肤说明移动到根目录后产生断链。未推送的本地提交对应链接须在发布后才能在线访问。

GitHub 也会自动提供标签的 Source code 压缩包。第三方源码获取地址和二进制构建来源见 [第三方说明](../THIRD_PARTY_NOTICES.md)。

## 本地生成相同目录结构

先保证工作区中的受跟踪文件已提交，并完成 EXE 构建与核验：

```powershell
.\.build-env\Scripts\python.exe tools/package_release.py --version v0.1.1
```

Windows 输出位于 `dist/release/v0.1.1/`。`tools/package_release.py` 使用明确的应用文档清单、Git 管理的示例与许可证，以及根目录十个皮肤；源码来自 `git archive HEAD`，不会递归收集工作区媒体或缓存。Linux 在对应系统运行 `build_desktop.sh` 生成 tar 包和核验报告，标签流程将它们合入发布目录并将两份文件的 SHA-256 追加到 `SHA256SUMS.txt`。仅本地运行 Windows 打包不会生成 Linux 附件。发布脚本不自动创建或推送标签。

校验一个下载文件：

```powershell
Get-FileHash .\osu-paint-v0.1.1-windows-x64.zip -Algorithm SHA256
```

将结果与同版本 `SHA256SUMS.txt` 对比。发布完成后检查七个 Release 附件齐全、标签指向正确提交、无需登录即可下载，并在干净目录解压运行。同步 README 下载版本、仓库 About 简介和主题；中文介绍可从 [宣传文案](promotion.md) 复制，实机演示须另外录制。

若自动发布失败，先查看失败步骤；修复权限或网络问题后，可在 Actions 重跑失败 job。已存在的同名 Release 不会被脚本静默覆盖。
