# Pixel Film 皮肤

[使用指南](usage.md) · [构建指南](building.md) · [研究索引](research/README.md)

## 选择与安装

用当前程序导出，分别导入 `pattern.osz` 和该次导出目录中匹配客户端、窗口比例的 `.osk`，在游戏中选择皮肤。已有同名版本时覆盖并重新载入，使用向下滚动、相同滚速、默认舞台缩放和 No Fail。

每次导出只生成目标客户端的五个比例，行高匹配实际画布。根目录和独立皮肤发布包中的十套皮肤默认 24 行；更换行数或更新位置算法后，应重新导出并同时更新谱面与皮肤。

| 窗口比例 | lazer 文件 | stable 文件 |
| --- | --- | --- |
| 16:10（默认，如 3072×1920） | `pixel-film-16x10.osk` | `pixel-film-stable-16x10.osk` |
| 16:9（如 1920×1080） | `pixel-film-16x9.osk` | `pixel-film-stable-16x9.osk` |
| 4:3（如 1024×768） | `pixel-film-4x3.osk` | `pixel-film-stable-4x3.osk` |
| 2560×1080 | `pixel-film-2560x1080.osk` | `pixel-film-stable-2560x1080.osk` |
| 3440×1440 | `pixel-film-3440x1440.osk` | `pixel-film-stable-3440x1440.osk` |

同一比例适用于多种分辨率，皮肤内部名称标明客户端、比例和行数。两客户端皮肤不可混用；旧导出目录中的历史文件不会自动删除。

## 布局与客户端限制

两套均包含 1–18K 配置。共同使用 `HitPosition: 480`、`WidthForNoteHeightScale: 480 / H`（H 为行数），列间距和列线为零。底边锚点、展示漂移与判定余量由 [时间模型](timing.md) 定义。

| 项目 | lazer | stable |
| --- | --- | --- |
| 列宽 | `480 × 窗口宽高比 / 键数`，无每列 100 上限 | 同一公式再钳制到每列最多 100，16:10 至少 8 列才能横向铺满 |
| 舞台 | 目标 `2026.921.0-lazer` 的 >10K 强制双舞台 | `SplitStages: 0` 合并 1–18K，保留奇数列 |
| 高键数 | 11/13/15/17K 分别变成 10/12/14/16 列；12/14/16/18K 保留列数但拆分 | 支持全部 1–18K |
| 1K 间距 | 按常规配置 | 必须省略 `ColumnSpacing`，空列表导致原生加载失败 |
| 底边资源 | 透明 `StageBottom` | 固定不透明白色遮挡，见下节 |

lazer 的 [legacy 解析器](https://github.com/ppy/osu/blob/master/osu.Game/Skinning/LegacyManiaSkinDecoder.cs) 直接读取列宽；[舞台配置](https://github.com/ppy/osu/blob/master/osu.Game/Skinning/LegacyManiaSkinConfiguration.cs) 未实现 `SplitStages` / `StageSeparation`，这些字段不写入 lazer 皮肤。[转换器](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Beatmaps/ManiaBeatmapConverter.cs) 在上述目标版本中对 >10K 先整数除 2 再建立两个等宽舞台，皮肤无法恢复丢列。链接供定位，结论以记录的目标版本为界。

stable 另设 `SpecialStyle: 0`、`ColumnStart: 0`、`ColumnRight: 0`，提供透明判定与警告资源。字段限制及原生解析依据见 [stable 皮肤证据](research/stable-skin-evidence.md)。

## 黑色资源与边缘采样

舞台背景为不透明白色，音符全部纯黑 `(0,0,0,255)`：

| 资源 | 尺寸与用途 |
| --- | --- |
| 短音符、长条头尾 | 1024×1024，保持正方形比例 |
| 长条身体 | 40×1024，拉伸连接头尾 |
| 边框、键位、灯光、判定线 | 透明隐藏 |

贴图尺寸不等于屏幕音符尺寸，实际行高仍由 `480 / H` 控制。[LegacyBodyPiece](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Skinning/Legacy/LegacyBodyPiece.cs) 的 Miss 颜色乘算保持黑色，整体 Alpha 淡出及物件生命周期仍由客户端决定。

**黑色 PNG 不等于绘制后纯黑。** 目标 `2026.921.0-lazer` 的框架使用 1024 图集，两侧各留 24，单图可用高度 976。纯黑边缘上传优化只比较 RGB，会跳过透明黑边缘；线性过滤因此混入透明像素。旧 40×1 身体四分之一处 Alpha 为 0.75，旧 40×40 头尾在边缘/角落分别为 0.5 / 0.25，白底混合后出现灰白线。

当前两类贴图的高度都超过 976，[TextureStore](https://github.com/ppy/osu-framework/blob/master/osu.Framework/Graphics/Textures/TextureStore.cs) 因而使用独立纹理与 `ClampToEdge`。框架策略探测和软件插值回归确认 Alpha 为 1；头尾边缘/角落的五比例 125 个采样中，旧资源 120 个失败，新资源全部通过。单张共享正方形资源的未压缩 RGBA 为 4 MiB，不是每个音符各占 4 MiB。

修改这些尺寸或采样策略必须保留边缘插值回归。此证据不能代替 GPU 实机、stable 采样或判定淡出验收；只更新 EXE 或谱面也不会替换游戏里已安装的旧皮肤。

## stable 固定底部遮挡

`StageBottom` 按键数引用 `pixel-bottom-N.png`，是白色舞台遮挡，音符头尾与身体仍全黑。高度为 1 个皮肤坐标单位，即舞台高度的 `1/480`，1920 高窗口约 4 像素。它配合编译器缩小画面间距，遮挡离场边缘。

原生舞台层以底部中心为原点，在音符之后绘制，不自动拉伸宽度；各贴图宽度因此取对应键数实际总列宽向上取整，低键数仍受 100 上限约束。五比例共 90 个配置已用目标 stable 原生解析器验证资源映射，PNG 检查覆盖不透明白色与尺寸。

**此修改需同时更新 `.osz` 与本次导出的 stable `.osk`。** 已有 JSON 重新导出即可，帧时间和音轨不动，不必重抽视频。原生移动对照中的内部白缝已消除，但整数裁剪仍可能短暂露出长条底边，有限换帧与未知相位依然存在；尚无 GPU 实机验收。机制和反例见 [stable 白缝记录](research/stable-white-seam.md)。

## 构建与验证

皮肤由 `osu_paint_skin.py` 唯一生成，`tools/build_skin.py` 默认重建根目录十套 24 行交付包；`--client lazer` / `stable` 可单独构建，`--rows 13` 可指定行数，提交前恢复默认两端 24 行。环境与命令见 [构建指南](building.md#皮肤构建)。

构建仅依赖标准库、固定 ZIP 元数据，交付包必须逐字节复现。回归检查所有键数与比例、资源引用、RGBA、图集与边缘采样、判定位置和导出行高；序列化积分及 Node / Tk 检查底边、行间连续与长条跨度。模型和原生解析结果不能保证所有显示相位下零残影。
