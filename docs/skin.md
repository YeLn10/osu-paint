# Pixel Film 皮肤

## 安装与外观

双击根目录 `pixel-film.osk` 导入，在游戏皮肤设置中选中 **osu-paint Pixel Film**。已有同名皮肤时覆盖更新，并重新载入皮肤。若谱面自带皮肤覆盖了外观，启用 **Ignore all beatmap skins（忽略所有谱面皮肤）**，优先采用所选皮肤。[官方设置说明](https://osu.ppy.sh/wiki/en/Client/Options#skin)

皮肤为每个 1–16K 独立定义 `[Mania]`，包含 11、13、15K。白色轨道上显示黑色方块：`#` 对应黑色音符，`.` 留白。普通音符与长条头尾为 40×40 不透明黑色 PNG，长条身体为 40×1 黑色 PNG，按长度拉伸。键位图、舞台边框、灯光和判定线贴图透明。

每列宽 40，列间距与列线宽为 0。判定位置设为 402，与生成器 stable legacy 基准一致；使用固定滚速、向下滚动、NF，stable 关闭 **Scale osu!mania scroll speed with BPM**。音符大小是皮肤属性，行间距是谱面属性，皮肤本身不会改变视频采样分辨率。

## 黑块修复与 stable 去分割

原包只有 16K 配置；普通音符使用白色贴图，长条头尾透明，仅长条身体为黑色。默认短音符在白轨道上不可见；其他键数没有对应配置，会回退到客户端默认配置。

现在每个键数的短音符、长条头、身体、尾部都引用不透明黑色资源，每列都有不透明白色背景。删除未使用的白色音符资源，防止只修了长条而漏掉默认短音符。

每个键数显式设置 `SplitStages: 0`，强制 stable 使用单舞台，10–16K 中央不再留双舞台间隙；并将列间距、列线、舞台边框设为零或透明。仅设置 `StageSeparation: 0` 不足以关闭舞台拆分。[官方 skin.ini 说明](https://osu.ppy.sh/wiki/en/Skinning/skin.ini)规定按键数分别配置，并支持强制合并舞台。

本机已有 stable 1.3.3.8 的只读诊断记录：`SkinMania` 创建任意列数的配置数组；缺少对应配置会新建默认配置。有效拆分值优先使用皮肤值，再使用 ≥10K / Co-op 默认值；`StageSeparation` 还会钳制为至少 5。客户端 SHA256 为 `C7B77C2F6FC458521114E06C197749601651E1BD4FEEBE503F457232702B16AB`。临时反编译文件已按清理要求移除，以上是本次采用的兼容结论。

## lazer 限制（2026-09-30 核查）

官方 [LegacyManiaSkinConfiguration](https://github.com/ppy/osu/blob/master/osu.Game/Skinning/LegacyManiaSkinConfiguration.cs) 将 `SplitStages`、`StageSeparation` 放在未实现属性区域。不能据此宣称 `.osk` 已解决 lazer 的双舞台。

官方 [ManiaBeatmapConverter](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Beatmaps/ManiaBeatmapConverter.cs) 对原生 mania 的 >9 列执行整数除 2，再建立两个等列数舞台。因此 10/12/14/16K 会拆分，11/13/15K 会分别变为 10/12/14 列；只增加皮肤配置无法恢复被转换器丢掉的列。完整支持需要客户端扩展或上游实现。原版客户端安装皮肤后仍需按这些边界使用。

本次按用户确认仅完成皮肤、文档和清理，暂不制作 lazer 扩展。

## 构建与验证

```powershell
python tools/build_skin.py
python -m unittest discover -s tests -p test_skin.py -v
```

构建脚本只用标准库，集中生成配置和三个 PNG，固定 ZIP 元数据。根目录 `.osk` 是版本管理的交付物，不手改压缩包；修改脚本后重新构建并一起提交。

回归直接读取交付的 `.osk`，检查全部 16 个配置、列数组长度、10–16K 的关闭拆分项、所有音符的实际 RGBA 像素、透明舞台资源、资源引用完整性、判定位置以及重建后的字节一致性。对原包运行回归时出现缺配置、白音符和判定位置不匹配的失败，修复后通过。完整测试共 140 项通过。验证没有启动客户端，不包含实机截图或 Miss 淡出验收。
