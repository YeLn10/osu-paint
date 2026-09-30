# Pixel Film：lazer 全屏皮肤

核查日期：2026-09-30。应用和皮肤仅适配 osu!lazer。生成器可写 1–18K，皮肤包含全部 18 个配置；原版客户端的 >9K 限制见下文。

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

每列背景为不透明白色，普通音符、长条头尾均引用 40×40 不透明纯黑 PNG，身体引用 40×1 不透明纯黑 PNG 并拉伸。所有像素都是 `(0,0,0,255)`，中间不使用灰色或半透明资源。lazer [LegacyBodyPiece](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Skinning/Legacy/LegacyBodyPiece.cs) 的 Miss 颜色乘算仍会让纯黑保持黑色；客户端的整体淡出及物件生命周期不能由贴图取消。舞台边框、键位、灯光和判定线资源透明。

原包的短音符为白色，长条头尾透明，只有 16K 配置，其他键数会回退。现在为全部 1–18K 指定完整黑色资源，删除无用白色音符贴图。

## 原版 lazer 的高键数边界

[LegacyManiaSkinConfiguration](https://github.com/ppy/osu/blob/master/osu.Game/Skinning/LegacyManiaSkinConfiguration.cs) 尚未实现 `SplitStages` / `StageSeparation`。这些字段无法强制 lazer 合并舞台，已从当前皮肤移除。

[ManiaBeatmapConverter](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/Beatmaps/ManiaBeatmapConverter.cs) 对原生 mania 的 >9 列先整数除 2，再建立两个等列数舞台。因此 10/12/14/16/18K 强制拆分，11/13/15/17K 分别变为 10/12/14/16 列。皮肤不能恢复转换时丢掉的列。1–9K 可以采用整幅宽度配置；>9K 的完整无分割画面需要客户端扩展或上游修改。

用户已确认暂不制作客户端扩展。当前交付包含 1–18K 导出和皮肤配置，不能视为原版 lazer 已完整实现无分割 1–18K。

## 构建与验证

```powershell
python tools/build_skin.py
python -m unittest discover -s tests -p test_skin.py -v
```

指定行数可用 `python tools/build_skin.py --rows 13`，提交前恢复默认 24 行。构建模块只用标准库，固定 ZIP 元数据；根目录五个 `.osk` 必须能从源码逐字节复现。

回归检查所有键数与比例的配置、实际 RGBA、资源引用、判定位置、按导出行数生成的高度及可复现性。位置检查重新解析 `.osu` 并独立积分，Node / Tk 检查全宽布局、底边锚点、行间连续和长条跨度。验证没有启动游戏，不包含实机显示、判定淡出、舞台缩放或刷新相位验收。
