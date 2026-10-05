# lazer 音符画面定格、音乐继续（2026-10-05）

## 结论与处理

本次记录中可确认的直接原因是客户端 `FrameStabilityContainer` 的时间差保护进入持续拒绝状态，不是导出文件缺少后半段。它会停止更新音符区域而不停止音频。最初为何出现足够大的时间差尚未确认，不能仅凭警告中的 BASS 名称认定音频驱动有错，也不能把单线程或显卡当成已证实根因。

观看这类谱面时，可退出当前游玩、启用 **Autoplay（AT）** 后重新播放。AT 使用回放处理器，避开本次确认的保护分支；只开 No Fail 不会避开它。**Cinema（CN）不适用**：虽然同样使用自动回放，`ModCinema<T>.ApplyToDrawableRuleset` 还会隐藏整个音符区域，而本项目的画面正是由音符组成。

本次没有修改客户端 DLL、游戏设置、谱面、音频或生成器。AT 是针对这一机制的绕过办法，不是客户端代码修复；还没有完成用户问题谱面开启 AT 后的整段实机验证。

## 版本与证据

直接检查已安装的程序集，而非用其他版本的实现代替：

- `osu.Game.dll`：`2026.921.0-lazer+aaa75b7c0a9f21d558ce84cd0ffac6c739bad8e7`。
- `osu.Framework.dll`：`2026.921.0+247dee9888c51606b939f027bce54504f8ca26fa`。
- 关键类型：`osu.Game.Rulesets.UI.FrameStabilityContainer`、`DrawableRuleset<T>`、`ManiaModAutoplay`、`ManiaFramedReplayInputHandler`、`ModCinema<T>`。
- 用 IL 字符串引用定位到 `FrameStabilityContainer.updateClock`，再反编译核对实际分支。该类型的远端源码下载遇到 TLS 错误，结论依据为本机实际 DLL。

2026-10-05 10:30:26（北京时间）的本地 runtime 日志连续出现十组：

```text
Ignoring likely invalid time value provided by BASS during gameplay
- provided: 39,496.67
- expected: 38,989.49
...
- provided: 39,623.17
- expected: 38,989.49
```

这些是毫秒值，不是帧编号。音频参考时间推进了 126.50 ms，待接受的画面时间没有推进；第一组差值为 507.18 ms。日志中的 `expected` 是尝试推进后的时间，不是已经显示的时间。该连续异常计数达到十次后不再输出，但拒绝逻辑仍在运行。

另外只读检查了一份本地导出：3288 帧、43535 个音符，重新解析实际 `.osu` 并按分段 float32 舍入积分，每帧中点的图案都匹配报告；后半段仍有持续变化。这只能验证该文件的生成几何，不能独自证明游戏正常，也不能代替对其他谱面的检查。

## 锁住的机制

1. `applyFrameStability` 发现画面时间落后时，分步推进，每步约 16.667 ms，避免直接跳过需要处理的帧。
2. 正式发行版、非 NUnit、非回放、启用帧稳定处理时，如果这一步的目标时间仍与音频参考时间相差超过 500 ms，且主游戏这一帧耗时不超过 500 ms，就被认为是可疑的音频时间。
3. 分支设置 `NotValid` 并提前返回，没有更新 `manualClock.CurrentTime`；`UpdateSubTree` 随即退出，不更新音符子树。
4. 下一帧仍从旧画面时间计算同一个目标时间。若音频继续向前，差值只会扩大，因而持续拒绝，形成定格。

这不是整个渲染器必须停止工作，也不要求某张谱面的 SV 算法有错。音频参考时钟与音符区域的本地时钟是不同层次，后者可以锁住而前者继续推进。

## 安装版本的隔离复现

本地探针直接引用安装目录中的原始程序集，不改 DLL，不加载个人媒体，也不启动游戏窗口或音频设备。以 `ManualClock` 代替外部时间输入，用主时钟的 16 ms 帧间隔和日志中的十个参考时间调用实际 `updateClock`；允许正常的 `RequiresCatchUp` 路径分步追赶。

必须以 **Release / `/optimize+`** 编译探针，确认 `Debug=False`、`NUnit=False`。Debug 和 NUnit 会跳过这条保护；普通调试运行得到绿色结果，并不能排除发行版中的定格。

首次待推进时间为日志中的 38989.49 ms，因此初始画面时间设置为 `38989.49 - 1000 / 60`，即约 38972.823333 ms。输入十个实测参考时间后，再模拟音频连续前进十秒。

| 检查 | 无回放处理器（普通游玩路径） | 实际 mania AT 回放处理器 |
| --- | --- | --- |
| 第一组音频时间 | 39496.67 ms | 39496.67 ms |
| 第一组画面时间 | 38972.823333 ms | 39496.67 ms |
| 第一组状态 | `NotValid` | `Valid` |
| 十秒后音频时间 | 49623.17 ms | 49623.17 ms |
| 十秒后画面时间 | 38972.823333 ms | 49623.17 ms |
| 画面继续推进断言 | 失败，退出码 1 | 通过，退出码 0 |

AT 对照不是把保护条件手动关掉：探针使用两个合成音符，经 `ManiaBeatmapConverter` 和 `ManiaModAutoplay.CreateReplayData` 生成回放，再创建实际的 `ManiaFramedReplayInputHandler`。客户端 `DrawableRuleset<T>.SetReplayScore` 会把同一个回放处理器连接到 `FrameStabilityContainer`；其 `hasReplayAttached` 条件使上述错误保护分支不再执行。

本地忽略目录 `build/freeze-diagnostics/` 保留 `ClockFreezeProbe.cs`、编译响应文件、已安装类型的反编译记录、`installed-clock-red.log` 与 `autoplay-clock-green.log`。它们不含个人媒体或凭据，不随项目提交；缓存不存在时仍可依据上述版本、类型和输入重新构造复现。复现命令为：

```powershell
$game = "$env:LOCALAPPDATA\osulazer\current"
dotnet exec --runtimeconfig "$game\osu!.runtimeconfig.json" --depsfile "$game\osu!.deps.json" build/freeze-diagnostics/ClockFreezeProbe.dll $game --assert-progress
# 同一个探针，唯一对照条件为接入实际 AT 回放处理器：
dotnet exec --runtimeconfig "$game\osu!.runtimeconfig.json" --depsfile "$game\osu!.deps.json" build/freeze-diagnostics/ClockFreezeProbe.dll $game --autoplay --assert-progress
```

## 尚未验证的边界

- 还没有定位最初的音频时间变化或画面追赶积压从哪里产生；不能宣称切换线程模式、渲染器或声卡一定能解决。
- 不修改客户端保护逻辑，不把反编译程序集或修改版客户端作为项目交付。
- 本探针验证时钟分支和 AT 处理器，不覆盖 GPU 绘制、实际设备音频、密集音符的整段性能或显示器采样相位。
- AT 不会解除原版 lazer 的 >10K 双舞台限制，也不构成实机零残影保证。

项目完整检查：`.\.build-env\Scripts\python.exe -m unittest discover -s tests -v`，138 项测试通过。本次仅修改文档，不需要重建 EXE 或皮肤。
