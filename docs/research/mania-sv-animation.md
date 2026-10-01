# osu!mania：用 SV / BPM 变速播放音符逐帧动画

核查日期：2026-09-29；包含 2026-09-28 的作品调查。目标按“用音符构成画面，而不是播放背景视频”理解。本次进一步明确目标为 osu!lazer，见第 4 节的解析边界和初版实现策略。

2026-09-30 后续修改：应用仅适配 lazer，保留滚速调节，改为完整上下范围、Pixel Film 判定位置 480、底边锚点和纯黑长条，按画布行数导出五种比例的 1–18K 配置。下文 658 px、20%–80%、1.1 倍推进距离和跨客户端讨论均是初版研究记录，不是当前使用规则；当前配置与高键数限制见 [皮肤说明](../skin.md)。

## 结论

**可以实现“近似停帧 → 快速推进一帧 → 近似停帧”的动画。已有作者作品及实际谱面数据作为证据；但不能把它理解为普通绿线提供了原生的零速、瞬时换图接口。** [S8][S9][S10]

- 狭义 SV（绿线倍率）有范围限制；低速不等于零速。[S2][S3]
- 广义滚速（BPM 红线 × SV 绿线）可实现很大的快慢比。查到的 16K《Bad Apple!!》实例实际仅用红线变速，不含绿线。[S5][S10]
- 所有帧先编码成纵向排列的音符图案，SV/BPM 只负责推动整条图案带。不是在换帧时替换音符贴图。[S6][S8]
- 本次完成官方文档、官方源码与作者公开文件的静态核查，**没有在本机运行 osu!stable 或 osu!lazer 验收**。未指定目标客户端时，不能承诺同一套极端参数跨版本可用。

## 1. 与本问题有关的变速形式

以下按速度曲线归类，不是游戏文件中独立存在的“动画类型”。[S1][S11][S12]

| 形式 | 构成 | 对动画的作用 |
| --- | --- | --- |
| 阶跃快慢切换 | 在指定时间切换恒定倍率 | 基础速度控制 |
| 渐快 / 渐慢 | 密集放置控制点，近似线性或缓动曲线 | 平滑移动，不是干净换帧 |
| Stutter 式变速 | 短快段与长慢段交替 | 间歇推进图案 |
| 近似停顿 + teleport 式推进 | 展示阶段极慢，换帧阶段快速移动一个帧间距 | 最接近用户的“快 → 停 → 快” |

### 绿线和真正零速

此次核查的官方 osu!lazer 源码快照：

- 提交：`1a84c00929fa70b23a20e8109af1289f34b50af2`（2026-09-28 的 master 快照，不等同于已安装的发行版本）。
- 负 beatLength 转倍率：SV = -100 / beatLength；beatLength 非负时走倍率 1 的分支。因此将绿线 beatLength 写为 0，不会得到停止。[S2]
- mania 使用 EffectControlPoint.ScrollSpeed，范围 **0.01–10**。别和标准模式滑条的 DifficultyControlPoint.SliderVelocity 下界 0.1 混为一谈。[S2][S3][S14]
- 负 beatLength 是文件编码约定，不表示负滚速。上述正常解析链没有提供零速或负向滚动；`NaN` 绿线也会解析成 1 倍，不是停止。[S2][S3][S5]
- 红线 BeatLength 被约束到 **6–60000 ms/beat**，即 **1–10000 BPM**。不能直接照搬其他客户端使用的更低 BPM 参数。[S2][S4]

### 滚动距离模型

在向下滚动、无额外速度 MOD、配置固定的条件下，可以用下面的等价数学模型设计画面：[S5][S6]

    effective_speed(t) = BPM(t) / reference_BPM × SV(t)
    S(t) = integral(effective_speed(t) dt)
    y_note(t) = y_hit - K × (S(note_time) - S(t))

K 由滚速设置、显示区域等条件决定。lazer 的顺序滚动算法确实按每段“时长 × 倍率”累计位置，再用音符时刻与当前时刻的累计位置之差绘制；mania 的默认计算消除了全局 SliderMultiplier 的影响，所以不能靠调该全局字段任意放大滚速。[S5][S6]

这意味着：

1. SV 控制的是整场纵向位移，不是每个像素的独立运动。
2. 需要按累计滚动距离而不是单纯按帧时间排列音符；多行像素不能都放在同一个判定时间上。
3. 可用反解 S 的方式求音符时间：S(note_time) = S(frame_time) + (y_hit - desired_y) / K。
4. 展示段要求 K × ΔS 小于允许漂移；换帧段要求 K × ΔS 接近一幅画面的纵向帧间距。

以上四点是基于源码模型的工程推导，不是已完成的运行测试。[S5][S6]

## 2. 实际作品：Promachos 的 16K Bad Apple!!

作者于 2023-02-10 提交谱面。其视频说明称用 Python 生成，以分层音符构成各帧，像胶片一样向下滚动。[S8][S9]

作者公开说明还要求：使用附带皮肤及实际 .osu 文件、打开 No Fail、滚速设置为 27；建议限制到 30 FPS 以减少抖动，并警告不要对这份作品使用 Auto，以免崩溃。这些是**该作品的要求**，不是对所有 SV 谱面的普遍断言。[S9]

### 对真实 .osu 的静态检查

本次从作者链接的 ZIP 通过 HTTP Range 只读取压缩目录、.osu 和 skin.ini，没有安装谱面、运行文件或下载其中的音视频。[S9][S10]

- ZIP 内实际 .osu 大小：6,275,122 字节。
- 音符：187,485 个；16 列；122,234 个普通音符、65,251 个长条。
- TimingPoints：13,139 个，**全部是红线；绿线 0 个**。
- [TimingPoints] 在源文件第 53 行，[HitObjects] 在第 13,195 行。
- 原始 .osu 的 SHA-256：`b46da731f581b90693d1fbd211132821ce19dd429942ce8905895a9121ce84ac`。

以上数字由公开源文件直接计数，非网页上占位难度的音符统计。[S10]

开头两组变速可概括为：[S10]

| 时间区间 | 原始 beatLength | 换算 BPM | 意图/效果解释 |
| --- | ---: | ---: | --- |
| 0–21 ms | 1,000,000 | 0.06 | 极慢展示 |
| 21–33 ms | 28.15 | 约 2131.44 | 快速推进 |
| 33–54 ms | 1,000,001 | 约 0.06 | 极慢展示下一帧 |
| 54–66 ms | 28.150001 | 约 2131.44 | 再次快速推进 |

之后大体以 33/34 ms 的周期重复，符合约 30 FPS；不是把 SV 设为精确 0。每一轮的原始 beatLength 有微小变化，不能简单删除这些变化并假定参考 BPM 不变。[S10][S5]

按源文件数值计算，首轮慢段/快段位移之比为：

    (21 / 1000000) / (12 / 28.15) = 0.0000492625

若快段推进 600 像素，慢段仅移动约 0.030 像素。这是比例推算，假设客户端按这些原始 beatLength 执行；不是本机像素测量，也不能套用到把低 BPM 钳制后的客户端。[S10][S12]

### 这个实例证明了什么、没证明什么

- 证明音符胶片式逐帧动画不是空想，并提供了可检查的变速布局。[S8][S10]
- 它不证明普通绿线能够真正停止，也不证明任意皮肤/滚速/刷新率都能无抖动。[S2][S3][S9]
- 原始慢段 0.06 BPM 超出了本次核查的 lazer 正常 TimingControlPoint 范围；导入后的时间点及参考 BPM 可能变化，不能保证原样重放。[S4][S5][S10]
- 本次没有确认演示所用客户端的精确构建，也没有重新运行 stable。stable 的精确上下界及极端值兼容性仍需要目标版本实测。

## 3. 对 osu-paint 的设计判断

**建议把它作为“音符图案带 + 累计滚动距离编排”来实现，而不是“每到一帧就将 SV 置零”。**

最小验证建议（尚未执行）：

1. 先固定目标客户端、皮肤、列宽、判定线位置、滚速和帧率；先做 A/B/C 三帧低分辨率图案。
2. 把每一帧排列在独立的累计滚动距离区间，留出上下边界余量；展示阶段极慢，换帧阶段恰好推进一个帧间距。
3. 验收：展示期漂移小于 1 像素、三帧边界位置误差小于 1 像素、没有稳定露出的相邻帧；再测不同渲染帧率是否采到换帧中的画面。
4. 最后再提升分辨率和帧率。换帧窗口、音符时间精度、可见区域裁剪与绘制负载必须一起验证，不能靠无上限拉高 SV 解决。

时间精度补充：这份作者谱面的音符开始时间全为整数毫秒；但当前 lazer 的 legacy parser 使用 double 读取开始时间与长条结束时间，不能由此泛化成“lazer 只支持整数毫秒”。stable 的小数时间行为本次未验证。[S7][S10]

## 4. 面向 lazer 初版程序的补充核查（2026-09-29）

再次访问官方仓库，`master` 仍为提交 `1a84c00929fa70b23a20e8109af1289f34b50af2`。以下是这个源码版本的结论，不能据此声称已经在用户安装的客户端上完成验收。[提交记录](https://github.com/ppy/osu/commit/1a84c00929fa70b23a20e8109af1289f34b50af2)

### 4.1 可用与不可用的速度编码

官方格式约定绿线使用负的逆速度百分比，例如 `beatLength=-50` 表示 2 倍。当前 lazer 的 mania 解析结果如下：[官方格式说明](https://osu.ppy.sh/wiki/en/Client/File_formats/osu_(file_format)#timing-points)、[固定版本解析器](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/Formats/LegacyBeatmapDecoder.cs#L484-L561)、[mania 滚速范围](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/ControlPoints/EffectControlPoint.cs#L22-L34)

| 绿线 beatLength | 公式结果 | mania 最终 SV | 说明 |
| --- | ---: | ---: | --- |
| `-10` | 10 | 10 | 绿线上限 |
| `-1` | 100 | 10 | 被范围约束 |
| `-100` | 1 | 1 | 正常 |
| `-1000` | 0.1 | 0.1 | 正常 |
| `-10000` | 0.01 | 0.01 | mania 绿线下限 |
| `-1000000` | 0.0001 | 0.01 | 不会继续变慢 |
| `0` 或正数 | 1 | 1 | 不会停止或反向 |
| `NaN` | 1 | 1 | 比较 `NaN < 0` 为假；源码专门解释这一行为 |

`NaN` 的历史兼容用途是禁用标准模式滑条 tick 生成，不能移植成 mania 零滚速。红线 `NaN` 则直接抛出无效数据异常。另外数字解析本身限制绝对值不超过 `2147483647`；`-1e12`、正负无穷不会成为绕过下限的方案，而是在进入滚速约束前解析失败。[NaN 处理](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/Formats/LegacyBeatmapDecoder.cs#L490-L550)、[数值边界](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/Formats/Parsing.cs#L16-L39)

所谓大于 10 或小于 0.1 的“SV”需要分清：0.01–0.1 本来就是 mania 允许的绿线倍率；超过绿线范围的**总滚动倍率**可以由红线 BPM 和绿线共同实现。固定参考 BPM 时，总倍率为 `SV × BPM / reference_BPM`。例如参考 120 BPM，1 BPM × 0.01 得到约 0.00008333 倍，10000 BPM × 10 得到约 833.33 倍。这个例子成立的前提是参考 BPM 确实保持为 120，不能只写红线就假定它保持不变。[倍率公式](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/Timing/MultiplierControlPoint.cs#L24)、[参考值归一化](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/UI/Scrolling/DrawableScrollingRuleset.cs#L108-L158)

`osu file format v128` 确实是 lazer 编码器写出的版本，但版本号不提供无限制滚速。检查的 `LegacyBeatmapDecoder` 仍用相同分支解析 TimingPoints，编码器把 mania 的 `EffectControlPoint.ScrollSpeed` 写回绿线。没有在该解析链找到可通过 `.osu` 文本设置的 `ScrollSpeedFactor` 字段；不要生成这个未经支持的字段，或把自定义 JSON 属性当成官方谱面接口。[v128 编码与 mania 绿线转换](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/Formats/LegacyBeatmapEncoder.cs#L24)、[转换实现](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/Formats/LegacyBeatmapEncoder.cs#L193-L214)

### 4.2 最容易使停帧失效的参考 BPM

mania 相对最常见 beatLength 归一化。“最常见”按红线覆盖的**时间总长**计算，不是按红线条数或音符数。源码具体行为：[Beatmap.GetMostCommonBeatLength](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/Beatmap.cs#L80-L120)

1. 第一条红线的计时起点强制当作 0；末段通常计算到最后音符结束时间。
2. 各 beatLength 先按 `Math.Round(beatLength × 1000) / 1000` 分组，即精确到 0.001 ms。
3. 累加每组持续时长，取最长的一组；返回结果再约束到实际 beatLength 最小值与最大值之间。

因此，长时间固定 1 BPM 会成为参考 BPM，使慢段总倍率重新变成 0.01。将 beatLength 每次仅增加 0.000001 的做法也不能可靠地分散时长分组。此前 Bad Apple 样例的微扰不能直接移植到当前 lazer；其超过 60000 的慢 beatLength 还会先被钳制成同一个值。

针对一个指定展示区间，可用以下**源码推导的实现方案，尚未游戏实测**：慢段切成短段，例如每段 50 ms，使用位于允许范围内、按 0.001 ms 舍入后仍互异的 beatLength，例如 `60000、59999.99、59999.98……`；每段均配 SV=0.01。正常 120 BPM 段的累计时长须大于每个慢段分组时长，随后按上述算法验证参考值确为 500 ms。不能让序列越过 6 ms 下限，也不能无限复用慢 beatLength 而忽略累计时长。初版应根据实际输出计算参考 BPM 和预计漂移，而不是隐藏这一依赖。

每一条红线都重新产生倍率为 1 的 effect point，因此每个慢段红线后要在**同一时间**写入 `-10000` 绿线；否则红线切换会恢复 1 倍。快段也要重新设置所需绿线倍率。[红线与 effect point 解析](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/Formats/LegacyBeatmapDecoder.cs#L530-L561)

### 4.3 图案、长条和显示时机

在向下、Sequential 滚动、无速度 MOD 的约束下定义：

```text
M(t) = reference_beat_length / beat_length(t) × SV(t)
S(t) = 分段积分 M(t) dt
distance_above_judgement(note_time, t) = scroll_length / time_range × (S(note_time) - S(t))
```

程序以展示开始时刻的目标纵坐标求出累计距离，再反解 `S(note_time)`。像素对应的音符判定时间通常落在展示区间结束后的快段，因此不能把“图案展示的时间”直接写成全部音符的判定时间。展示期间应让整个图案留在判定线上方，避免音符被判定和移除。[位置与反解实现](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/UI/Scrolling/Algorithms/SequentialScrollAlgorithm.cs#L29-L79)

LN 的头、尾都按累计距离定位，条身几何长度为 `scroll_length / time_range × (S(end_time) - S(start_time))`，并受皮肤头尾尺寸和判定后的遮罩影响。它不等于“持续毫秒数 × 当前瞬时速度”。音符的显示寿命起点也由滚动算法反解，因此长时间慢速并不意味着图案会因为超过常规时间窗口而自动不可见；实际皮肤尺寸、判定、裁剪仍需游戏验收。[布局与寿命](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/UI/Scrolling/ScrollingHitObjectContainer.cs#L204-L288)、[LN 身体尺寸和遮罩](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game.Rulesets.Mania/Objects/Drawables/DrawableHoldNote.cs#L237-L292)

lazer mania 的基础 `time_range = 11485 / 用户滚速`，运行时还会随皮肤判定线位置及速度 MOD 调整。因而程序的像素定位需要约定滚速与皮肤/坐标标尺；不能承诺任意配置都得到同样像素位置。[滚速与皮肤校正](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game.Rulesets.Mania/UI/DrawableManiaRuleset.cs#L158-L183)

初版可先用 `#`/`.` 文本矩阵生成普通音符，每列对应一个按键列，输入毫秒区间，输出 `.osu`、SV 控制点和模型预览。成功标准是：区间起点各音符达到指定相对坐标，整个展示段漂移在给定容差内，出场快段把图案送过判定线；若目标过长或设置不满足误差容限，明确报告模型误差。纯绿线固定 BPM 的最简方案也可实现，但长展示段会明显漂移，不能标成真正静止。

**证据边界：** 当前已完成官方文档与固定提交源码核查。上述分段近停与反解是可实现的数学策略；本次研究没有启动 osu!lazer，没有测量实际帧率、皮肤像素或导入后表现。有限速度的“快进”具有非零持续时间，不能保证所有显示刷新时刻都避开切换过程。

## 5. 自由时间表与极速清场（2026-09-29）

对同一固定提交重新读取 `TimingControlPoint`、`EffectControlPoint` 和 mania 的 `DrawableNote`、`DrawableManiaHitObject`：

- 红线 beatLength 最小值仍为 6，绿线 SV 最大值仍为 10，因此参考 beatLength 为 500 时，最大有效倍率为 `500 / 6 × 10 ≈ 833.333`。不能继续写超界参数来获得更高速度。
- `DrawableNote.CheckForResult` 会在音符不可再命中时才自动判漏接；`DrawableManiaHitObject.UpdateHitStateTransforms` 在 Miss 后执行 150 ms 淡出。音符判定时间不等于立刻从画面删除的时间。[音符判定](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game.Rulesets.Mania/Objects/Drawables/DrawableNote.cs)、[漏接淡出](https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game.Rulesets.Mania/Objects/Drawables/DrawableManiaHitObject.cs)

因此采用实际滚动清场：每次推进 1.1 个判定线上方区域高度，极速时间为 `ceil(1.1 × time_range / (500 / 6 × 10) × 1000) / 1000` ms，向上取整到微秒以避免导出时超过速度上限。滚速 27 得到 0.575 ms。图案最高点在 0.2 高度以下，推进后超过 1.3；默认完整舞台为 `768 / 658 ≈ 1.167`，留出音符自身高度的余量。

自由模式保留输入的每帧起止时刻。相邻间隔至少等于一次推进时间：间隔不超过两倍时共用一次推进，速度按间隔调整；更大的空档分别执行退场与进场，中间回到正常 BPM，下一帧保持在屏幕上方。所有展示段的慢 beatLength 跨帧保持互异，仍检查参考 BPM。

验证独立解析导出 `.osu` 并积分，覆盖展示起止坐标、空档无音符（包含判定线下方）、滚速 1/15/27/40、120 帧、速度上下界及完整舞台清场。旧版 12 ms 在帧结束后 5 ms 仍有音符位于舞台内；新版默认滚速 27 在结束后 1 ms 已清场。桌面和 HTML 预览都保留音符过判定线后的几何位置，不使用提前隐藏来掩盖退场。

**范围：以上为源码与导出数据验证；尚未在用户安装的 lazer 中实测。有限速度无法保证所有刷新时刻都避开过渡，皮肤与游戏内滚速必须匹配。**

## 一手来源

网页资料按 2026-09-28 访问；源码链接固定到上述提交。源文件统计及公式推导已分别标明。

- [S1] 官方 mania mapping guide（SV 影响滚速、BPM 联动）：`https://osu.ppy.sh/wiki/en/Guides/osu%21mania_mapping_guide`
- [S2] 官方 LegacyBeatmapDecoder（倍率解析及 mania 使用 EffectPoint）：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/Formats/LegacyBeatmapDecoder.cs#L488-L559`
- [S3] 官方 EffectControlPoint（0.01–10）：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/ControlPoints/EffectControlPoint.cs#L22-L34`
- [S4] 官方 TimingControlPoint（6–60000 ms）：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/ControlPoints/TimingControlPoint.cs#L65-L83`
- [S5] 官方综合倍率公式：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/Timing/MultiplierControlPoint.cs#L24`；参考 beatLength：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/UI/Scrolling/DrawableScrollingRuleset.cs#L108-L158`；mania 的全局倍率处理：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game.Rulesets.Mania/UI/DrawableManiaRuleset.cs#L90-L94`
- [S6] 官方顺序滚动的位置积分与差分：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/UI/Scrolling/Algorithms/SequentialScrollAlgorithm.cs#L41-L44`；`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/UI/Scrolling/Algorithms/SequentialScrollAlgorithm.cs#L70-L135`
- [S7] 官方音符时间解析：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/Objects/Legacy/ConvertHitObjectParser.cs#L64`；`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Rulesets/Objects/Legacy/ConvertHitObjectParser.cs#L167-L186`
- [S8] 作者演示视频与说明：`https://www.youtube.com/watch?v=gSptX551Jw8`
- [S9] 作者谱面页及使用要求：`https://osu.ppy.sh/beatmapsets/1937932`
- [S10] 作者谱面页链接的原始源包：`https://promachos.s-ul.eu/Ulb4vqhq`。核查对象是包内含“Use NF + Scrollspeed 27”的 .osu，以及 skin.ini；校验值见上文。
- [S11] Agka 自己的 SV 工具（分段、渐变、函数曲线；其老工具限制不代替当前 mania 引擎限制）：`https://zardoru.github.io/sv-tools/`
- [S12] 原研究者关于 BPM/SV × 时间与距离的推导：`https://niv.gay/osumania-research-lab/Distance_Measuring.html`
- [S13] 官方 mania 用户滚速及 BPM scaling 说明：`https://osu.ppy.sh/wiki/en/Game_mode/osu%21mania`
- [S14] 官方标准滑条倍率范围，用于和 mania 区分：`https://github.com/ppy/osu/blob/1a84c00929fa70b23a20e8109af1289f34b50af2/osu.Game/Beatmaps/ControlPoints/DifficultyControlPoint.cs#L24-L27`
