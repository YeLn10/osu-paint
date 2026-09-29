# stable 实验兼容记录

核查日期：2026-09-30。

本机安装配置 `LastVersion` 为 `b20260412.1`，EXE 文件版本为 `1.3.3.8`，两者不是同一个版本字段。只读取安装与版本相关信息，没有读取或上传登录凭据。客户端可以启动；尝试实机检查时用户操作并最小化了窗口，随后按 Esc 停止电脑控制，已停止界面操作。当前没有游戏内图案位置验收结果。

## 一手资料与实现边界

- [官方 osu 格式说明](https://osu.ppy.sh/wiki/en/Client/File_formats/osu_(file_format)#hit-objects) 把音符时间定义为整数毫秒。本模式遵守这一格式，不依赖小数音符时间。
- [官方 mania 设置说明](https://osu.ppy.sh/wiki/en/Game_mode/osu%21mania#bpm-scaling-and-fixed-scroll-speed) 区分 BPM scaling 与 fixed scroll speed；fixed 仍接受谱面 BPM/SV 变化。要求关闭 Scale osu!mania scroll speed with BPM，不是启用恒速 MOD。
- [官方 legacy 皮肤兼容代码](https://github.com/ppy/osu/blob/master/osu.Game/Skinning/LegacyManiaSkinConfiguration.cs) 记录默认判定线位置 402；[滚速兼容代码](https://github.com/ppy/osu/blob/master/osu.Game.Rulesets.Mania/UI/DrawableManiaRuleset.cs) 用 `11485 / scrollSpeed` 并按判定线高度校正。stable 模式采用传统默认基准 `11485 / scrollSpeed`；这是依据官方兼容实现的模型，并非对闭源 stable 当前二进制的精确重现。
- stable 参考源码链接当前不可公开读取，未据此声称已核对所有解析边界。保留原有红线 6–60000 ms、SV 0.01–10 的保守范围；参考 BPM 分组仍使用项目已有模型，需要实机进一步校验。

## 整数时间策略

简单地把现有亚毫秒换帧谱面的音符时间取整，会让多行落在同一毫秒。stable 模式先把切帧时间增至至少 `2 × 行数` ms，再反解每行音符时间并取整；各行原始时间间距至少 `0.6 / 行数 × 切帧时长 / 1.1 > 1 ms`。自动化验证检查输出中各行仍有不同时间，位置量化误差不超过半行。

每帧加入 `切帧时长 + 1 ms` 的 500 ms beatLength / SV=0.01 段，使参考 BPM 段的累计时间超过快进段；保留实际漂移报告。每帧展示至少比该段长 1 ms，所以导入周期须至少 `2 × 切帧时长 + 2 ms`。这是本生成器为兼容采取的限制，不是声称 stable 引擎只支持这个 FPS。

测试覆盖 1、6、24、128 行、1000 帧的参考 BPM，以及真实带音乐视频导入。测试是独立解析导出数据并积分的模型测试，不替代游戏渲染验收。

## 转换预览验证

使用本地生成的灰度 80 / 120 图案，默认阈值 128 时不显示；降低阈值或调整亮度／对比度后恢复右半轮廓，反转恢复左半轮廓。对可变帧率合成视频，验证拉伸、等比留边、等比裁剪及多组帧序号的预览与整段导入逐像素一致。预览选帧位于 FPS 重采样之后，序号不是原视频编码帧编号。
