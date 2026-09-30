# Pixel Film 皮肤

## 安装与外观

先用新版本 osu-paint 重新导出，再双击导出目录中匹配游戏窗口比例的 `.osk`，在游戏皮肤设置中选择对应 Pixel Film 皮肤。已有同名皮肤时覆盖更新，并重新载入皮肤。若谱面自带皮肤覆盖了外观，启用 **Ignore all beatmap skins（忽略所有谱面皮肤）**，优先采用所选皮肤。[官方设置说明](https://osu.ppy.sh/wiki/en/Client/Options#skin)

皮肤为每个 1–18K 独立定义 `[Mania]`，包含 11、13、15、17K。白色轨道上显示黑色方块：`#` 对应黑色音符，`.` 留白。普通音符与长条头尾为 40×40 不透明黑色 PNG，长条身体为 40×1 黑色 PNG，按长度拉伸。键位图、舞台边框、灯光和判定线贴图透明。

使用固定滚速、向下滚动、NF，stable 关闭 **Scale osu!mania scroll speed with BPM**。旧谱面按旧判定位置生成，需要重新导出；仅替换皮肤会使位置不匹配。

## 全屏与常用分辨率

五个版本均包含完整 1–18K 配置；按游戏实际窗口比例选择，同一比例可适配多种分辨率，无需为每种像素尺寸复制一份。

| 文件 | 适用屏幕 / 窗口 | stable 能铺满横向的键数 |
| --- | --- | --- |
| `pixel-film.osk` | 16:10：3072×1920、1920×1200、2560×1600 | 8–18K |
| `pixel-film-16x9.osk` | 16:9：1280×720、1920×1080、2560×1440、3840×2160 | 9–18K |
| `pixel-film-4x3.osk` | 4:3：1024×768、1600×1200 | 7–18K |
| `pixel-film-2560x1080.osk` | 2560×1080 | 12–18K |
| `pixel-film-3440x1440.osk` | 3440×1440 | 12–18K |

默认对应用户的 3072×1920。列宽为 `min(480 × 屏幕宽高比 / 键数, 100)`，列间距、列线均为零，横向起点为 0。stable 每列最大宽度为 100；低键数按用户选择保留真实键数并使用最大宽度，不补空白列，因此表中下限以下不能铺满横向。这些版本共用该宽度限制。

纵向判定位置设为 `HitPosition: 480`，生成器将 H 行的中心放在 `(row + 0.5) / H`，覆盖顶部到底部。方形音符使用 `WidthForNoteHeightScale: 480 / H`，让显示高度独立于列宽，避免行间留缝。皮肤坐标按 480 高度缩放；生成器对应内部 768 高度，时间范围为 `11485 / scrollSpeed × 480 / 402`。[官方配置说明](https://osu.ppy.sh/wiki/en/Skinning/skin.ini)与 [lazer 音符缩放实现](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Skinning/Legacy/LegacyNotePiece.cs)支持上述坐标与高度设置。

**每次导出自动生成按实际画布行数匹配的五个皮肤**，包括视频因刷新率预算降采样后的实际行数。请优先使用该次导出目录中的皮肤；根目录交付包默认只对应 24 行。不同画布行数需要各自的匹配皮肤。桌面与 HTML 预览显示默认 16:10、白底黑块和低键数最大宽度，不模拟客户端的舞台缩放、判定或淡出。

## 黑块修复与 stable 去分割

原包只有 16K 配置；普通音符使用白色贴图，长条头尾透明，仅长条身体为黑色。默认短音符在白轨道上不可见；其他键数没有对应配置，会回退到客户端默认配置。

现在每个键数的短音符、长条头、身体、尾部都引用不透明黑色资源，每列都有不透明白色背景。删除未使用的白色音符资源，防止只修了长条而漏掉默认短音符。

每个键数显式设置 `SplitStages: 0`，强制 stable 使用单舞台，10–18K 中央不再留双舞台间隙；并将列间距、列线、舞台边框设为零或透明。仅设置 `StageSeparation: 0` 不足以关闭舞台拆分。[官方 skin.ini 说明](https://osu.ppy.sh/wiki/en/Skinning/skin.ini)规定按键数分别配置，并支持强制合并舞台。

本机已有 stable 1.3.3.8 的只读诊断记录：`SkinMania` 创建任意列数的配置数组；缺少对应配置会新建默认配置。有效拆分值优先使用皮肤值，再使用 ≥10K / Co-op 默认值；`StageSeparation` 还会钳制为至少 5。客户端 SHA256 为 `C7B77C2F6FC458521114E06C197749601651E1BD4FEEBE503F457232702B16AB`。临时反编译文件已按清理要求移除，以上是本次采用的兼容结论。

## lazer 限制（2026-09-30 核查）

官方 [LegacyManiaSkinConfiguration](https://github.com/ppy/osu/blob/master/osu.Game/Skinning/LegacyManiaSkinConfiguration.cs) 将 `SplitStages`、`StageSeparation` 放在未实现属性区域。不能据此宣称 `.osk` 已解决 lazer 的双舞台。

官方 [ManiaBeatmapConverter](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Beatmaps/ManiaBeatmapConverter.cs) 对原生 mania 的 >9 列执行整数除 2，再建立两个等列数舞台。因此 10/12/14/16/18K 会拆分，11/13/15/17K 会分别变为 10/12/14/16 列；只增加皮肤配置无法恢复被转换器丢掉的列。完整支持需要客户端扩展或上游实现。原版 lazer 的 >9K 无法仅靠这些皮肤实现整幅无分割全屏，安装后仍需按这些边界使用。

本次按用户确认仅完成皮肤、文档和清理，暂不制作 lazer 扩展。

## 构建与验证

```powershell
python tools/build_skin.py
python -m unittest discover -s tests -p test_skin.py -v
```

核心皮肤模块只用标准库，集中生成配置和三个 PNG，固定 ZIP 元数据，由应用导出与构建脚本共用。手动重建指定行数可用 `python tools/build_skin.py --rows 13`；提交前恢复默认 24 行构建。根目录五个 `.osk` 是版本管理的交付物，不手改压缩包；修改模块后重新构建并一起提交。

回归直接读取交付的 `.osk`，检查全部 18 个配置、五种比例的列宽上限、关闭拆分项、所有音符的实际 RGBA 像素、透明舞台资源、资源引用完整性、判定位置以及重建后的字节一致性。导出回归另检查实际行数对应的皮肤高度、序列化 `.osu` 的全高行中心，以及 Node / Tk 绘制的短音符和长条能覆盖所有格子。验证没有启动客户端，不包含实机截图或 Miss 淡出验收。
