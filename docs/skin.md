# Pixel Film：lazer 全屏皮肤

核查日期：2026-10-01。应用和皮肤仅适配 osu!lazer。生成器可写 1–18K，皮肤包含全部 18 个配置；目标原版客户端的 >10K 限制见下文。

## 安装

用当前应用重新导出，导入 `pattern.osz`，再双击该次导出目录中匹配游戏窗口比例的 `.osk`，在 lazer 设置中选择该皮肤。已有同名皮肤时覆盖并重新载入。使用向下滚动、No Fail、与生成时相同的滚速以及默认舞台缩放。旧谱面的位置和尺寸不会因替换皮肤自动更新，必须重新导出。

## 常用屏幕比例

| 文件 | 屏幕 / 游戏窗口示例 |
| --- | --- |
| `pixel-film.osk` | 16:10：3072×1920、1920×1200、2560×1600 |
| `pixel-film-16x9.osk` | 16:9：1280×720、1920×1080、2560×1440、3840×2160 |
| `pixel-film-4x3.osk` | 4:3：1024×768、1600×1200 |
| `pixel-film-2560x1080.osk` | 2560×1080 |
| `pixel-film-3440x1440.osk` | 3440×1440 |

默认版本对应用户的 3072×1920。同一比例可用于多种像素尺寸。列宽为 `480 × 窗口宽高比 / 键数`，列间距和列线为零。lazer 的 [legacy 皮肤解析器](https://github.com/ppy/osu/blob/master/osu.Game/Skinning/LegacyManiaSkinDecoder.cs) 直接读取列宽，没有每列最大 100 的钳制；因此低键数可以保留真实键数并铺满横向。旧的宽度上限和其他客户端专用舞台配置已移除。

## 纵向位置与黑色长条

判定位置为 `HitPosition: 480`，音符高度为 `WidthForNoteHeightScale: 480 / H`，H 是本次画布行数。每次导出都会生成匹配实际 H 的五个皮肤；根目录交付包默认仅对应 24 行。更换画布行数后需导入该次导出的皮肤。

lazer 向下滚动的 [legacy 音符贴图](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Skinning/Legacy/LegacyNotePiece.cs) 按底边锚定。生成器将第 row 行底边放在 `(row + 1) / H`，再扣除整幅复用画面的漂移和约 `1 / 768` 的判定余量。贴图向上延伸一行，顶部按屏幕裁剪；底部余量约为 1 个内部像素，3072×1920 下约 2.5 屏幕像素，展示开始还包含微小漂移余量。这避免底部头音符在展示期间提前进入判定并淡出。桌面和 HTML 采用相同底边几何，修复原中心模型造成的半格偏移。

每列背景为不透明白色，普通音符、长条头尾均引用 1024×1024 不透明纯黑 PNG，身体引用 40×1024 不透明纯黑 PNG 并拉伸。头尾贴图保持原 40×40 的正方形宽高比，实际音符高度仍由 `WidthForNoteHeightScale: 480 / H` 决定，不是把音符画成 1024 像素高。所有像素都是 `(0,0,0,255)`，中间不使用灰色或半透明资源。lazer [LegacyBodyPiece](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Skinning/Legacy/LegacyBodyPiece.cs) 的 Miss 颜色乘算仍会让纯黑保持黑色；客户端的整体淡出及物件生命周期不能由贴图取消。舞台边框、键位、灯光和判定线资源透明。

截图中的灰色来自贴图采样。已安装的 `2026.921.0-lazer` 所带框架采用 1024 像素纹理图集，两边各预留 24 像素，单图可用高度为 976。图集边缘上传优化只比较 RGB，纯黑边缘会被当成已有黑色而跳过上传，透明边缘于是保留下来。原来的 40×1 身体被拉伸时，线性过滤混入透明边缘，在白色背景上显成灰色；检查 PNG 本身的 RGBA 不足以发现这一问题。

新的身体高度 1024 超过图集可用高度，[TextureStore](https://github.com/ppy/osu-framework/blob/master/osu.Framework/Graphics/Textures/TextureStore.cs) 因而使用独立纹理和 `ClampToEdge`，采样不再混入图集透明边缘。此修复只更换皮肤资源，不改客户端。诊断对已安装框架的图集策略进行了探测，再独立计算线性采样：旧资源四分之一处 Alpha 为 0.75，新资源为 1，白底混合结果从灰色变成纯黑。

2026-10-03 补齐头尾边缘修复：此前只处理长条身体，普通短音符及长条头尾的 40×40 贴图仍会进入同一个图集。它们在边界也会混入透明黑色：边缘中心 Alpha 为 0.5，角落为 0.25，在白色舞台上出现灰白细线，亚像素移动时明暗随采样位置变化。改为 1024×1024 正方形贴图后，同样走独立纹理与 `ClampToEdge`，不改变长宽比、判定位置或谱面几何。共享贴图的未压缩 RGBA 数据从约 6 KiB 增至 4 MiB，这是单张资源大小，不是每个音符各占 4 MiB。

新增采样回归覆盖五种交付皮肤、水平／垂直边缘和角落共 125 个位置，旧资源有 120 个采样失败，新资源全部为不透明黑色；原长条身体采样和整幅位置回归继续保留。此项基于已记录的目标框架图集行为和软件插值模型，没有宣称消除客户端淡出、有限切帧间隙或显示器实机的全部白线。需导入匹配画布行数的新版 `.osk`，覆盖同名皮肤并重新载入；只替换 EXE 或谱面不会更新已安装皮肤。

原包的短音符为白色，长条头尾透明，只有 16K 配置，其他键数会回退。现在为全部 1–18K 指定完整黑色资源，删除无用白色音符贴图。

## 原版 lazer 的高键数边界

[LegacyManiaSkinConfiguration](https://github.com/ppy/osu/blob/master/osu.Game/Skinning/LegacyManiaSkinConfiguration.cs) 尚未实现 `SplitStages` / `StageSeparation`。这些字段无法强制 lazer 合并舞台，已从当前皮肤移除。

[ManiaBeatmapConverter](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Beatmaps/ManiaBeatmapConverter.cs) 在已安装 `2026.921.0-lazer` 中对原生 mania 的 >10 列先整数除 2，再建立两个等列数舞台。12/14/16/18K 保留列数但拆分，11/13/15/17K 分别变为 10/12/14/16 列。皮肤不能恢复转换时丢掉的列。1–10K 可以采用整幅宽度配置；早期文档将边界写为 >9K，本次以目标程序集的执行结果更正。

## 构建与验证

```powershell
python tools/build_skin.py
python -m unittest discover -s tests -p test_skin.py -v
```

指定行数可用 `python tools/build_skin.py --rows 13`，提交前恢复默认 24 行。构建模块只用标准库，固定 ZIP 元数据；根目录五个 `.osk` 必须能从源码逐字节复现。

回归检查所有键数与比例的配置、实际 RGBA、图集分配及边缘线性采样、资源引用、判定位置、按导出行数生成的高度及可复现性。位置检查重新解析 `.osu` 并独立积分，Node / Tk 检查全宽布局、底边锚点、行间连续和长条跨度。验证没有启动游戏；框架策略探测和采样计算不能替代 GPU 实机显示、判定淡出、舞台缩放或刷新相位验收。

2026-10-03 交付验证：完整 137 项回归通过；按脚本重建根目录五个皮肤与 EXE，核对五个内置模块与源码一致，执行包内桌面入口确认默认长条，并从包内构建模块逐字节复现五套交付皮肤。边缘对照与验收摘要分别为 `build/white-edge-comparison.json`、`build/white-edge-validation.json`；缓存不进入 Git。
