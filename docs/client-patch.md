# 可添加、可删除的 Pixel Film 客户端补丁

目标：Windows osu!lazer `2026.921.0-lazer`，规则集 API `2026.818.0`。这是官方自定义规则集入口加载的本地观影模式，显示名称为 **Pixel Film**，内部名称为 `pixel-film`，OnlineID 为 -1。普通 osu!mania 保留原有行为；Pixel Film 不提交官方 mania 成绩。

## 安装与卸载

1. 使用当前 `dist/osu-paint.exe` 重新导出并导入 `.osz`。旧导出缺少完整帧数据和 Pixel Film 入口谱面，需要重导。
2. 关闭 lazer，双击 `dist/pixel-film-patch/install.cmd`。安装器检查官方程序集及补丁哈希，只在数据目录 `rulesets/` 添加 `osu.Game.Rulesets.PixelFilm.dll` 和 `pixel-film-install.json`。
3. 重启 lazer，在模式选择中选 **Pixel Film**，播放刚导入的 **Pixel Film N columns** 难度。若选曲列表隐藏了转换谱面，开启“显示转换谱面”。该模式自动切换画面，无需调相位、NF 或皮肤，画布随窗口铺满。Esc 暂停及退出仍由客户端处理。
4. 卸载时关闭 lazer，双击同目录的 `uninstall.cmd`。它只删除收据登记且哈希一致的补丁 DLL 和收据。重启后继续使用原版模式，已有谱面、音轨、皮肤和数据保留。

默认游戏目录为 `%LocalAppData%/osulazer/current`，数据目录为 `%AppData%/osu`。修改过数据位置时，安装／卸载必须传同一个实际数据目录；可在游戏中“打开 osu! 文件夹”确认：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File dist/pixel-film-patch/manage-patch.ps1 -Action Install -StorageDirectory "D:\MyLazerData"
powershell -NoProfile -ExecutionPolicy Bypass -File dist/pixel-film-patch/manage-patch.ps1 -Action Uninstall -StorageDirectory "D:\MyLazerData"
```

安装不替换官方 EXE、DLL、配置或数据库，不配置全局启动钩子。同名但未由本安装器登记的 DLL 不会被覆盖或删除；已安装 DLL 被修改时卸载停止，保留修改后的文件。重复安装和卸载可安全执行。客户端运行时禁止装卸。

更新补丁时先运行卸载，再安装新包。官方客户端升级后，补丁指纹校验会拒绝旧包。仍可卸载旧补丁；新版本需先核对 API、重新适配和测试，再更新 `client_patch/compatibility.json`，不能仅删掉版本检查。

## 启动加载失败修复（2026-10-01）

若启动时提示 Pixel Film 加载失败，日志中的调用链为 `RealmRulesetStore.testRulesetCompatibility` → `FilmBeatmapConverter.ConvertBeatmap`，并报 `Re-export this map with osu-paint`，原因是旧补丁误拒绝了客户端启动自检的空谱面，不是影片本身损坏。

目标客户端会直接转换一个空 `Beatmap`，不先调用 `CanConvert()`。补丁现在仅对无音符、无 Source 的空探针返回合法的单列空舞台，不生成片尾标记；`CanConvert()` 与选曲过滤仍拒绝非影片，带音符的普通谱面、损坏的影片标记及帧文件校验规则保持不变。关闭游戏后按上面的卸载、安装步骤更新补丁；已有包含 `pixel-film.osu` 和 `pixel-film.json` 的正确导出无需重导。

回归直接调用目标程序集的真实启动兼容性检查，使用不连接数据库的隔离对象；另检查空探针不被视为可播放影片、无额外完成标记，以及非影片和损坏标记仍被拒绝。旧补丁在该检查中复现同一异常，修复后通过；此检查不等于游戏窗口及 GPU 显示验收。

## 完整帧显示

导出新增 `pixel-film.json` 和 `pixel-film.osu`，同时放入 `.osz`。帧文件包含版本、列数、行数、原有时间窗口和 `#` / `.` 行数组，不含本地视频路径。两个 `.osu` 的标准 `Source` 字段记录 `协议 结束时间 列数 SHA-256`。客户端通过当前谱面资源接口读取帧文件，校验配对关系及尺寸、时间、像素预算；数据缺失或不匹配会拒绝播放，要求重新导出。

原版选曲只允许标准 osu! 谱面转换到自定义模式，mania 难度会被隐藏。入口 `pixel-film.osu` 因而使用 `Mode: 0`、合法的 CS 5 和一个片尾标记；实际列数从绑定的 Source 读取，不用 CS 表示。普通 mania 难度仍在 `pattern.osu`，两个难度共用帧文件和音轨，不复制媒体。入口只有正常 BPM，不能把它当作普通 mania 的音符动画使用。

生成器仍是时间模型的唯一来源。极速换帧间的短清场空隙在客户端数据中延续上一整帧到下一帧开始，主动长空档仍留白。不同画面的边界采用 `[开始, 结束)`，边界处直接选新画面，结束后留白；暂停和回退按同一个游戏时钟重新选帧，音轨不移动。

规则集转换器保留 1–18 列的单舞台，使用片尾时间建立一个不可见完成标记，使客户端在片尾正常完成播放。画面由独立 Sprite 绘制，纹理采用最近邻采样、`ClampToEdge` 和不透明黑白像素；相同画面复用纹理。每次更新只切换完整纹理，没有下落音符、长条身体渐变或新旧画面混合。关闭常规游戏 HUD，让画布覆盖可用游戏区域。

这解决的是软件生成的滚动过渡及混帧。显示器响应拖影、系统合成器撕裂和掉帧属于另一层，不能据此保证物理屏幕零残影。实际 GPU、音画同步及用户窗口仍需实机验收；默认游戏缩放使用完整区域。

## 构建与验证

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File client_patch/build.ps1
.\.build-env\Scripts\python.exe -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File build_desktop.ps1
```

构建使用本地 .NET SDK 的 C# 编译器，以目标客户端自带托管程序集为引用，不复制客户端程序集到补丁包，不下载第三方注入库。目标指纹见兼容清单；运行时也检查相同三份程序集。

检查包括：原版 11–18K 分割／少列、默认键位表超范围及选曲隐藏 mania 的失败对照；补丁 1–18K 单舞台、模式身份、入口可选、实际 WorkingBeatmap 编译流程及片尾完成；60／120／165 Hz 下 100 个相位共 12,000 次采样；数据损坏与谱面绑定；目标框架无窗口宿主中的依赖加载、完整 Sprite 边界切换、纹理分配及无人按键的完成事件；隔离目录中的重复安装、卸载、版本拒绝、同名及修改文件保护、客户端与数据不变。装卸测试使用合成文件并模拟进程清单，不读写用户存档。无窗口宿主采用 Dummy renderer，此结果不等于实际 GPU 或游戏窗口验收。

本次在检测到游戏已关闭后安装补丁，仅在个人数据目录的 `rulesets/` 新增自己的 DLL 和收据；未启动或关闭用户游戏窗口。测试只写项目的 `build/`、`dist/`，个人媒体和存档不进入 Git。

## 版本依据

- 当前客户端的 `osu!.runtimeconfig.json` 禁用启动钩子，所以选择可撤销的官方规则集加载入口。[RulesetStore](https://github.com/ppy/osu/blob/master/osu.Game/Rulesets/RulesetStore.cs) 在数据目录 `rulesets/` 发现符合命名的 DLL。
- 已安装的 Mania 常量 `MAX_STAGE_KEYS = 10`。原版 10K 是单舞台；11／13／15／17K 转为 10／12／14／16 列，12／14／16／18K 保留列数但双舞台。早期文档将分割阈值写为 >9K 不准确，本次以目标程序集的执行结果更正。
- 直接呈现使用 [IWorkingBeatmap.GetStream](https://github.com/ppy/osu/blob/master/osu.Game/Beatmaps/IWorkingBeatmap.cs) 和游戏时钟，不靠推测屏幕呈现相位。
- [RealmArchiveModelImporter](https://github.com/ppy/osu/blob/master/osu.Game/Database/RealmArchiveModelImporter.cs) 保存归档中的全部文件，帧 JSON 可通过谱面资源接口读取；[选曲筛选](https://github.com/ppy/osu/blob/master/osu.Game/Screens/Select/BeatmapCarouselFilterMatching.cs) 的转换限制也已对目标程序集直接执行检查。
