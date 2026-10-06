# osu!stable mania 绘画皮肤：几何与资源证据

核查日期：2026-10-04。范围仅为 **stable 的皮肤解析、舞台/列布局、贴图及 HUD 隐藏**；不研究谱面时间、SV、BPM、transform 时间或主编译器算法。

## 1. 结论与证据边界

- **已证实（本机二进制静态）：列宽是 `List<float>`，但每个有效有限值随后钳制到 `5–100`。** “支持小数”和“没有宽度上限”是两回事；不能移植 lazer 的无限列宽结论。[B1][B3][B4]
- **已证实（皮肤/布局链）：1–18 的全部整数键数均能保留全部列，包括 11/13/15/17。** 配置读取接受这些值，单舞台创建全部 N 列；双舞台按 `ceil(N/2)` 与剩余列分配，不是两边都向下取整。这里的前提是谱面加载后确实向布局传入 N；谱面解码、实际键位绑定和实机绘制另行验收。[B2][B5][B6]
- **已证实（静态）：`SplitStages: 0` 可以覆盖默认分舞台；默认从 10K 起分舞台。** 1K 始终单舞台。`StageSeparation: 0` 会变成 5，因此连续画布应合并舞台，不能靠把双舞台间距写 0。[B1][B5][B6]
- **全列保留不等于全屏。** 例如 16:10 至少需要 8 个物理列、16:9 至少 9 个，才能在每列不超过 100、零列间距的条件下覆盖全宽。保持更低真实 K 时只能接受较窄画布，或者由生成器另行增加/复用物理列；皮肤不能替它复制音符。[B1][B4][B5][B10]
- 建议基线为 `Version: 2.7`、`SplitStages: 0`、`ColumnStart: 0`、`ColumnRight: 0`、`HitPosition: 480`、`NoteBodyStyle: 0`、`UpsideDown: 0`。`ColumnStartSpecial` 暂不作为可依赖接口。[B1][B5][W1]
- **待实机：** 实际视口四边、亚像素接缝、透明头尾后的身体边界、GPU 采样、失误/按住时的透明度及完整 HUD 消除。本文没有启动游戏，没有把静态推导称作截图验收，也没有使用 lazer 行为证明 stable。

### 本机样本与方法

本机样本：`D:\ProgramFiles\osu!\osu!.exe`，大小 **4,541,216 bytes**；文件属性 `FileVersion = ProductVersion = 1.3.3.8`；SHA-256：

```text
3adc2d001aacced5f92ba8ae24121980d5e23f5653f37d14cf4765bca1abd9f9
```

这个通用文件版本号不足以确定对外发布的 stable 构建日期，因此本报告的二进制结论以 **上述哈希** 为边界，不笼统声称所有历史 stable 版本如此。使用已安装的 ILSpy CLI `9.1.0.7988` 静态反编译；没有执行游戏入口、反射调用游戏方法、修改安装目录或用户配置。

官方英文 osu-wiki 固定到提交 `c287c6013b9a5e878dfc2c2b9e338322ccd5e1c6`（2026-10-03 UTC）。本次有界查阅官方配置、mania 资源、FAQ、界面与快捷键文档、一个历史配置快照，以及指定参考皮肤；后续通过本机补充核查，对皮肤解析和直接布局/缩放调用链作静态核查。**发生冲突时，以该本机样本的可定位解析代码判断该样本，保留 wiki 原文差异。** 没有下载作者音视频或皮肤包。

## 2. 字段的真实类型、范围与限制

下表中的“无额外钳制”仅指所检查的字段读取步骤；不代表任意值都能在屏幕上有效显示。导出应使用有限数值，不把 NaN、无穷或非法枚举当作绕过限制的方法。

| 字段 | 本机样本的读取/范围 | 建议与边界 | 证据 |
| --- | --- | --- | --- |
| `Keys` | `int.TryParse`；`0–18` 可进入 `SkinMania` 构造；负值、>18、解析失败变成 0。实际画布使用 **1–18**，0 不是有列的正常画布。 | 每个 K 独立 `[Mania]`，显式写整数。wiki 仅列 1–10、12/14/16/18，**该列表不能当作本机拒绝奇数高 K 的证据**。 | 已证实（静态）：[B2]；文档差异：[W1] |
| `SplitStages` | `bool?`；有效值覆盖默认状态。默认是 `N >= 10` 或 Co-op；1K 清除覆盖并不分舞台。 | 写 `0` 强制单舞台；公开文档的 0/1 足够，不依赖额外布尔拼写。 | 已证实（静态）：[B1][B3][B6]；[W1] |
| `ColumnWidth` | **`List<float>`，逐项 `clamp(value, 5f, 100f)`**；默认每列 30。 | 允许分数列宽，不必进行整数列宽分摊；必须在钳制之后核算总宽。有限值如 4.5→5、100.1→100，53.333333 保留为 float32 近似值。 | 已证实（静态）：[B1][B3][B4] |
| `ColumnStart` | `float`，默认 136；读取时没有独立数值钳制。布局时还受视口宽度与右侧保留量共同限制。 | 从左边覆盖画布用 0；不能只改列宽却保留默认 136。负数不作为全屏方案。 | 已证实（静态）：[B1][B5]；[W1] |
| `ColumnRight` | `float`，默认 19；布局计算将它作为**右侧保留量**参与超宽缩放，不是最后一列的绝对 X 坐标。 | 全宽基线写 0；保留默认 19 可能使原本按全宽计算的列被缩小。 | 已证实（静态）：[B1][B5]；wiki 的说明较含糊：[W1] |
| `ColumnStartSpecial` | 本次固定 wiki 未列出；本机 `SkinMania` 没有同名字段，其专门加载步骤只见 `ColumnStart`、`ColumnRight` 等字段。 | **未证实，不写入建议配置。** 本机字符串键有混淆，本次未完整反解所有键名/别名，故不把“未发现”夸大为所有版本都会拒绝或忽略它；也不推测它能解除宽屏偏移。 | 证据缺口：[B1][W1]；效果待专门验证 |
| `StageSeparation` | `float`，默认 40；读取后 `Math.Max(value, 5f)`；未见上限钳制。 | 0 和负数都不能消除双舞台间隙。单舞台不添加该间距，可省略该字段。 | 已证实（静态）：[B1][B5] |
| `HitPosition` | **`int`，钳制到 240–480**；默认 402。 | 全高选 480；480.0 不是可依赖的整数写法。不能用 1000 把判定线移出屏幕，它会回到 480。 | 已证实（静态）：[B1][B3]；[W1] |
| `WidthForNoteHeightScale` | **`float`**，字段默认 0，读取时无额外钳制。绘制时 >0 才采用，否则回退到最窄列的有效宽度。 | 它是缩放参考宽度，**不是无条件等于音符像素高度**；还要乘贴图高宽比。正方形短音符在默认全高舞台可取 `480 / 画布行数`，非整数结果不应强制取整。0 不是“隐藏头尾”。 | 已证实（静态）：[B1][B5][B7]；[W1][W2] |
| `NoteBodyStyle` / `NoteBodyStyle#` | 按枚举解析。命名值为 **0=Stretch、2=RepeatTop、3=RepeatBottom、4=RepeatTopAndBottom**。皮肤 >=2.5 时逐列覆盖优先，然后全局值，缺省为 RepeatBottom；<2.5 强制 Stretch。 | 推荐显式 `0`。wiki 列 0/1/2、默认 1；本机数值 1 虽非命名枚举，仍可被 `Enum.Parse` 接受，并落入身体重复绘制的默认分支，效果分支与 3 相同。不要将 wiki 列表误当成严格拒绝 3/4。 | 已证实（静态）：[B1][B3][B8][B9]；文档差异：[W1] |
| `ColumnSpacing` | `List<float>`，默认 0；第 i 个间距下限为 `-ColumnWidth[i+1]`。 | 连续画布用 N−1 个 0；1K 必须省略该列表，不能输出空 `ColumnSpacing:`（见下方导入回归）。增加间距不会增加音符宽度，透明空隙不能替代像素列。 | 已证实（静态）：[B1]；透明间隙：[W1] |
| `ColumnLineWidth` | `List<float>`，默认 2；`0 < value < 2` 会抬到 2，0 保留。 | 用 N+1 个 0 真正关闭分隔线，不能写很小的正数假装关闭。 | 已证实（静态）：[B1] |
| `BarlineHeight` / `JudgementLine` | 前者 `float`，默认 1.2；后者 `bool`，默认 true。 | `BarlineHeight: 0`、`JudgementLine: 0`；仍需隐藏 `StageHint` 贴图。 | 已证实（静态）：[B1]；[W1] |
| `ScorePosition` / `ComboPosition` / `LightPosition` | **`int`**；默认分别为 325/111/413；本次读取步骤没有额外钳制。 | 1000 可作为前两者移出画面的候选，但它们只控制判定图/连击位置，**不是整个 HUD 的开关**。是否完全不可见仍须实机。 | 类型/读取已证实：[B1][B3]；含义：[W1] |

### 解析要点

`Components.Section` 对列表先按逗号切分，再根据列表元素类型转换；标量走 `Convert.ChangeType(string, targetType, numberFormat)`，枚举走 `Enum.Parse`。因此 **列宽、起点、间距、音符高度参考不是整数；判定线位置与判定/连击位置是整数**。对整数位置写带小数的字符串不是先解析浮点再截断：转换失败后，`Skin` 的读取函数不覆盖原字段。[B2][B3]

对列宽/线宽等初始长度非零的列表，正常缺项会保留构造默认值，多项会截到目标列表长度；导出仍应完整写 N 个列宽、N+1 个线宽，不依赖缺项回退。对于列表中的非法单项，`Section` 的递归转换返回值未被逐项检查，不能假定会像标量一样安全保留旧值。[B1][B2][B3]

### 2026-10-04 导入失败复查：空列表不是缺省列表

用户导入的 `pixel-film/skin.ini` 在 stable 的 `error.txt` 留下 `System.NullReferenceException`，调用栈为 `Skin.#=z8BNQ1xE=<T>` → `SkinMania.#=znYWNvKo=` → `Skin.#=zc595eik=`。压缩包已成功解压，故不是 ZIP 损坏。

对同一哈希程序集，在独立 32 位 PowerShell 中创建 `SkinOsu` 并只调用文件解析方法，不启动游戏。最小输入为 `[General] / Version: 2.7 / [Mania] / Keys: 1 / ColumnSpacing:`：稳定复现同一异常；仅删除空 `ColumnSpacing:` 后通过。用户 12 行配置只删除此行后，全部 1–18K 都通过。原因是 `Section.#=zoSqkm38=` 将空字符串的引用类型返回为 null 且表示成功，而 `Skin.#=z8BNQ1xE=<T>` 随后访问 `list.Count`。

修复后，根目录五个 24 行包与独立重新导出的五个 12 行包，共十个配置均经原生解析器确认包含完整 1–18K。`tests/test_skin.py` 同时约束实际交付包和按画布行数重建的包：1K 不含该字段，2–18K 保持 N−1 个零。回归修复前十个子案例失败，修复后通过。

临时复现脚本与结果保留在忽略的 `build/import-debug/`。以上增加的是实际 stable 文件解析证据，不是 GPU 渲染、皮肤热重载或完整游戏流程验收。

## 3. 全屏几何：可行范围与缩放

### 3.1 480 坐标系不等于所有宽高都整数化

官方说明以高度 480 为横向位置参照；本机舞台默认高度 480，判定位置通过 `stageTop + HitPosition × stageHeight / 480` 映射。默认向下滚动、未缩小舞台时，`HitPosition: 480` 才把判定位置放到舞台底部。[W1][B5]

设实际**渲染视口**宽高为 w、h（不是简单读取显示器标称分辨率）：理想逻辑总宽 `W* = 480 × w / h`。本机屏幕几何类用于布局边界的宽度则是：

```text
scale = float32(h) / 480f
layoutWidth = ceil(float32(w) / scale)
```

例如 1920×1080 的理想宽为 853.333…，布局边界为 854。**这是总视口边界向上取整，不是 ColumnWidth 按整数解析。** 均分 `W* / N` 可以使用小数；右边界不足一个逻辑单位的裁剪/覆盖差异与 float32 累加仍须截图核查。使用 `layoutWidth / N` 是略微向右过扫描的另一选择，不能把两种方案混称为严格相同几何。[B3][B10][B11]

stable 选项包含分辨率、全屏及 letterboxing 的位置调整；皮肤不能控制这些。验收必须记录实际视口，并避免把带黑边的小视口误当作整块显示器。[W4]

此外，本机屏幕几何类设置尺寸时会把 `h > 0.8 × w` 限为整数 `0.8 × w`；本文五种横屏比例没有触及该分支，不将表中结论扩展到竖屏/过高窗口。它与 letterboxing 的最终组合效果仍待实机。[B10]

### 3.2 零间距画布的列数下界

`ColumnStart = ColumnRight = 0`、单舞台、列间距全 0 时，总宽是各个**钳制后的**列宽之和。布局对超出可用宽度的总宽做横向缩小；总宽不足时不会自动放大补齐。不要通过写超大列宽期待解除 100 上限，也不要忽略默认左右保留量。[B1][B4][B5]

| 视口比例/示例 | 理想逻辑总宽 W* | 本机布局边界（该示例） | 每列 ≤100 的最少物理列数 | 16K 的建议均分列宽（十进制近似） |
| --- | ---: | ---: | ---: | ---: |
| 16:10，3072×1920 | 768 | 768 | **8** | 48 |
| 16:9，1920×1080 | 853.333333 | 854 | **9** | 53.333333 |
| 4:3，1024×768 | 640 | 640 | **7** | 40 |
| 2560×1080 | 1137.777778 | 1138 | **12** | 71.111111 |
| 3440×1440 | 1146.666667 | 1147 | **12** | 71.666667 |

表中下界为 `ceil(W* / 100)`，由已核查解析与布局公式推导，不是运行游戏得出的测量。另行做了五组算术核对。[B1][B4][B5][B10][B11]

因此，独立版本可以承诺“皮肤/布局支持 1–18K”，但不能同时无条件承诺“保持任意低 K 且覆盖同一宽屏”。如需增加物理列来表达低列数画面，属于主代理负责的生成/映射选择，本报告不实施。没有必要仅为规避所谓 stable 奇数高 K 丢列而强制把 11/13/15/17 补成偶数；该样本的分配代码保留余数。[B2][B5][B6]

### 3.3 可交给构建器的布局片段

以下是 **16:10、16K、24 行、正方形短音符**的布局基线，尚需补齐下一节的逐列图像映射和透明资源；不是完整可安装皮肤。[B1][B5][B7][W1]

```ini
[General]
Name: osu-paint stable Pixel Film
Author: osu-paint
Version: 2.7

[Mania]
Keys: 16
SplitStages: 0
SpecialStyle: 0
ColumnStart: 0
ColumnRight: 0
ColumnWidth: 48,48,48,48,48,48,48,48,48,48,48,48,48,48,48,48
ColumnSpacing: 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
ColumnLineWidth: 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
HitPosition: 480
WidthForNoteHeightScale: 20
UpsideDown: 0
NoteBodyStyle: 0
BarlineHeight: 0
JudgementLine: 0
ScorePosition: 1000
ComboPosition: 1000
```

其他行数可以保留 `480 / H` 的小数结果；若改为长条身体承担绘画、头尾透明，必须单独检查身体边界，不能只用这个短音符高度公式声称所有长条几何已经一致。[B7][B9]

## 4. 透明头尾、纯黑身体与参考皮肤

### 4.1 本地实例真正包含什么

参考文件为 [指定的 skin.ini][L1]（75 行，SHA-256 `b6d6fc55cb81f1548546827ed0da95a5095cd314fdf09cdc6a40b03eb6d08e37`）。它写有 `Name: osu! Default Skin Template`、`Author: Developers`，但**目录名和作者字段不证明这些已修改资源就是官方原版默认皮肤**。

- 16K：`SplitStages: 0`、16 个交替的 33/34 列宽（合计 **536**）、17 个 0 线宽、`BarlineHeight: 0`、全部白色不透明列背景。[L1]
- 18K：仅指定键数、0 线宽、0 小节线和合并舞台；没有独立列宽或白色列背景配置。[L1]
- 两节都没有 `ColumnStart: 0`、`ColumnRight: 0`、`HitPosition: 480` 或 `WidthForNoteHeightScale`。它是**合并舞台的绘画实例，不是本次全屏参数的证据**。[L1][B1]

用本机现有 Pillow 只读解码全部 12 个 `mania-note*.png`，得到以下实际 RGBA，而不是只根据文件名判断：[L2]

| 资源组（1/2/S 三种全部检查） | 尺寸 | 全图像素 | 结论 |
| --- | --- | --- | --- |
| `mania-note{1,2,S}.png` | 256×262 | `(136,136,136,255)` | 普通音符是灰色，不是纯黑 |
| `mania-note{1,2,S}H.png` | 256×82 | `(0,0,0,255)` | **头部不透明黑色** |
| `mania-note{1,2,S}L-0.png` | 256×82 | `(0,0,0,255)` | 身体不透明黑色，使用动画第 0 帧命名 |
| `mania-note{1,2,S}T.png` | 256×82 | `(0,0,0,0)` | **只有尾部全透明** |

同组 H/L/T 的三个文件各自同哈希，代表值如下，方便将来确认参考没有被替换：[L2]

```text
H: d6f8d3a5cb0e09a648215c2c3969da14675c8e7e999940a25c769ce8b1e4f633
L: 0d80c2a56257f8f19bf6f322b1057f198f246ee3300875b9d53e3286494031f0
T: f92e9182042dda3106bf5fc331475c51bc826bbbf62bea8e56ce8bf376647be9
```

[Promachos 的公开作品页][A1]确实列出 16K 作品并链接其皮肤/.osu 源包；本次没有下载该包或重新证明本地文件与线上包逐字节相等。不能把本地透明尾部改写成作者验证过“透明头尾”、任意 K 全屏或任意显卡无接缝。

### 4.2 独立皮肤的资源要求

**已证实（接口）：** 每列可以分别映射普通音符、H 头、L 身体和 T 尾。头尾及普通音符使用列宽/参考宽度缩放；尾图缺省会回退到头图。隐藏必须提供真正透明的资源，不能只删除文件，缺图可能回退到默认元素。[B1][B7][W1][W2][W3]

若主代理选择“身体承担黑色画面、头尾不可见”，建议自行生成、逐列引用：

- `NoteImage{i}H: blank`、`NoteImage{i}T: blank`，`blank.png` 全部像素 Alpha=0。
- `NoteImage{i}L: pixel-body`，身体全图 `(0,0,0,255)`，显式 `NoteBodyStyle: 0` 拉伸。
- 若仍有普通短音符绘画，`NoteImage{i}: pixel-black` 必须保留不透明黑色；不要为了隐藏 H/T 顺带把普通音符隐藏。
- i 从 **0 到 N−1**；白背景用 `Colour1` 至 `ColourN: 255,255,255,255`，颜色编号从 **1** 开始。[B1][W1]

上述透明头尾是**基于已证实映射接口的建议方案，尚未实机验证**，不是对参考皮肤的照抄。透明 PNG 仍有尺寸，身体位置计算会使用头图的几何高度；Alpha=0 不会自动把几何高度变成 0。需要主代理与实际身体端点一起验收，不在本报告推导时间补偿。[B7][B9]

`ColourHold` 控制长按期间的**连击计数颜色**，不是将身体强制变黑的字段。[W1] 黑色文件是必要条件，但不能证明绘制后的身体在所有状态仍为不透明纯黑：采样、混合及客户端淡出要实机检查。现有 lazer 导出的 40×1024 身体/1024×1024 头尾来自另一客户端的图集绕过方案，本次没有找到其为 stable 必需的证据，不将这些尺寸包装为 stable 限制。[T1]

高分辨率模式会优先使用 `@2x`，没有时才回退普通图片。新皮肤应使用干净的独立目录，或者保证同名 `@2x` 与动画帧也符合透明/纯黑要求，避免旧的可见帧覆盖新空白图；本次没有复制作者任何 PNG 或媒体。[W3]

## 5. HUD 与非画布元素隐藏

### 皮肤应负责的部分

1. `StageLeft`、`StageRight`、`StageBottom`、`StageHint`、`StageLight`、`LightingN`、`LightingL`、`WarningArrow` 引用存在的透明图；`KeyImage{i}` 与 `KeyImage{i}D` 也逐列透明。关闭 `JudgementLine` 不会代替隐藏 `StageHint`。[W1][W2][W3]
2. 关闭列线/小节线；可同时将 `ColourColumnLine`、`ColourBarline` 写成透明 RGBA。背景仍应是不透明白色，不要把列背景随装饰一起清空。[B1][W1]
3. 判定图可通过 `Hit0`、`Hit50`、`Hit100`、`Hit200`、`Hit300`、`Hit300g` 显式映射空白。`ScorePosition` 指判定图位置，不是顶端总分。`ComboPosition` 只处理连击计数。[W1][W2]
4. 通用分数/连击数字、血条、输入叠层、连击插图是另一批资源；如果希望在不隐藏界面时也没有图形，应单独处理 `score-*`、`scorebar-*`、`inputoverlay-*`、`comboburst-mania*` 的适用资源与帧。仅导出一张 `blank.png` 和几个舞台映射并不能覆盖整套 HUD；输入叠层数字等也不能仅靠清空其背景来隐藏。[W2][W6]

### 需要用户在客户端选择的部分（本次未操作）

- 官方快捷键 **Shift+Tab** 切换隐藏游戏内界面；观看回放/观战时 **H** 控制排行榜与回放界面。它们是客户端操作，不是 skin.ini 字段。[W5]
- 关闭 `Show leaderboard during gameplay`、`Always show key overlay`、`Show FPS counter`；`Score meter type` 选 `None`；关闭 `Combo bursts`。不要把官方 `Progress display` 列表中不存在的 `None` 写成已证实选项。[W4]
- 不需要媒体叠加时关闭背景视频/故事板，选择合适的背景 dim，并留意休息段亮度变化；白色不透明列背景应由皮肤本身保证，而不是依赖背景图片恰好是白色。[W1][W4]
- 应选中独立皮肤；若谱面附带皮肤元素，确认 `Ignore all beatmap skins` 的取舍，避免谱面元素覆盖验收使用的皮肤。[W4]

**待实机：** Shift+Tab 后实际剩余哪些 mania 专属元素、判定图/连击是否彻底消失、回放按钮、开场警告、休息段与输入叠层是否仍进入画布。不能把“HUD 已隐藏”仅凭配置文件判为通过。

## 6. 对目前导出副本的最小建议（未修改源码）

只读检查的 [目标皮肤构建模块][T1]目前仍是 lazer 方案。需由主代理决定/实施的差异限于：

| 当前情况 | stable 建议 |
| --- | --- |
| 直接用 `480 × aspect / keys`，未处理 100 上限 | 保留浮点列宽，但在 stable 的 5–100 范围与实际总宽约束下规划物理列。低 K 是否接受非全宽或增加物理列须明确，不默默钳制后仍标为全屏。 |
| 没有显式 `SplitStages`、`ColumnStart`、`ColumnRight` | 各 K 写 `0/0/0`；不需要用 `ColumnStartSpecial` 猜测兼容行为。 |
| `HitPosition: 480`、浮点 `480/H` | 前者适合本机范围；后者保留浮点，不要错误地一律改成整数。注意非正方形资源的高宽比。 |
| 普通音符和 H/T 都引用黑色图 | 若目标是透明 H/T，只改 H/T 映射，保持普通音符与身体按绘画方案可见；参考皮肤不证明透明头部方案已验收。 |
| 仅少量舞台/灯光资源为空白 | 补齐需要隐藏的键位、判定图及适用 HUD 资源；保留客户端手动隐藏步骤。 |
| 大纹理注释与测试依据是 lazer 图集 | 不当作 stable 的结论；是否保留尺寸作为实现选择，与是否已证实 stable 无采样灰边分开记录。 |

这些建议分别来自第 2–5 节的 stable/官方证据，不把目标副本作为 stable 实现证据。本次没有编辑该模块、AGENTS、其他文档、皮肤包或应用。

## 7. 验证清单与本次完成程度

| 检查 | 本次状态 | 后续通过标准 |
| --- | --- | --- |
| 解析类型、钳制和默认值 | **已完成静态核查**；含 float 宽度 5–100、整数 HitPosition 240–480、间距下限 5 | 如 EXE 哈希更换，重新核查相同调用链 |
| 1–18K 列分配 | **已完成静态核查及 36 组独立算术检查**（18 K × 单/双舞台）；不是游戏运行测试 | 实际加载对应 N，用列标识图确认 11/13/15/17 最后一列也出现；确认无意外键数 MOD |
| 五种比例全宽条件 | **已完成算术检查** | 记录视口和皮肤版本，检查四边与每个列边界；特别覆盖低 K 不可全宽的情况 |
| 参考资源 RGBA | **已完成 12 PNG 只读检查** | 新生成资源重新检查包括 `@2x`/动画帧在内的 Alpha 和颜色 |
| 身体/透明 H/T/HUD/GPU | **未做实机** | 静止及运动截图、按住/松开/失误状态、顶部/底部裁剪、单列交替黑白、HUD 开关对照均无未解释覆盖或细缝 |

算术与像素元数据只缓存于 `D:\osu-tools\osu-paint-stable\build\stable-skin-inspection`，并非把游戏渲染替换为自建模型后宣称验收通过。本次只交付本文；没有运行应用构建或完整源码测试，因为没有改应用源码。

## 8. 一手来源与复核定位

### 官方与作者资料

- **W1 — [官方 skin.ini 英文源][W1]**：版本说明 L74–100；Mania 总则/Keys L435–480；几何 L481–585；样式/颜色/贴图映射 L657–799。当前页对列宽仅写数字列表，没有给出 5–100；该上下限来自本机二进制。另对照了 [2017 年官方快照][W0]，未将历史列表当作本机运行上限。
- **W2 — [官方 mania 资源说明][W2]**：普通音符、长条头/身体/尾部的缩放、原点、回退、帧命名与舞台装饰。
- **W3 — [官方 Skinning FAQ][W3]**：HD/SD 回退 L188–201；隐藏元素需透明图 L253–255。
- **W4 — [官方 stable 客户端选项][W4]**：视口/letterboxing L117–128；图形开关 L130–140；HUD L174–210；皮肤覆盖 L262–271。
- **W5 — [官方快捷键][W5]**：游戏内 Shift+Tab、回放/观战 H，L133–145。
- **W6 — [官方界面资源说明][W6]**：输入叠层 L978–1020；血条 L1116–1222；分数数字 L1224–1477；输入叠层的数字还涉及 scoreentry 资源 L1910 起。
- **A1 — [Promachos 作品发布页][A1]**：作者的 16K 作品及源包链接。仅作作品来源线索，不代替本机全屏测试。
- **L1 — [指定本地 skin.ini][L1]**：L48–75；校验值、实际配置见第 4 节。
- **L2 — [本地 PNG 检查元数据][L2]**：对 `D:\osu-tools\bad apple mania\osu!Default Skin` 的只读解码；保存尺寸、颜色极值、单色计数和每文件 SHA-256，没有保存或复制作者图片。

### 本机原始二进制与派生的只读核查材料

以下 C# 是上述哈希 EXE 的反编译缓存，不是另一个客户端的源代码；它们在忽略的 build 目录，不随本文提交。混淆方法名可用对应类型、字段及 IL 常量复核。可复现基本命令为：

```powershell
ilspycmd -t 'osu.Graphics.Skinning.SkinMania' 'D:\ProgramFiles\osu!\osu!.exe'
ilspycmd -t 'osu.Graphics.Skinning.Components.Section' 'D:\ProgramFiles\osu!\osu!.exe'
```

- **B1 — [SkinMania][B1]**：字段/默认值 L34–96；列宽回调 L28–31；加载和钳制 L133–171；身体样式选取 L251–257。
- **B2 — [Skin][B2]**：Keys L84–125；失败不覆盖标量 L179–190；列表长度与回调 L234–257。
- **B3 — [Components.Section][B3]**：转换入口 L112–133；列表/类型转换 L149–214。
- **B4 — [FloatHelpers][B4]**：类型 `#=zYY7fvBq6mENKFnyGh7dvltw=` 的 `#=zWoRj$p9$AJQN(float,float,float)`，L628–642，确认是上下界钳制而不是仅接收两个无关参数。
- **B5 — [StageLayout][B5]**：类型 `#=zwRa71lIOJzp$VMz5GAIPMvqFKXMiXgXUZ6jFFXlCr061mPsS9IUeb_4=`；默认舞台尺寸 L251–257；横向适配及列构造 L341–362；第二舞台 L406–411；高度缩放 L837–869；分列 L916–937。
- **B6 — [SkinSelection][B6]**：类型 `#=zG02ojZuVFALqSV0BNA4gBW_qN97uuidEqg==`；按完整 Columns 匹配及默认分舞台 L440–459。
- **B7 — [NoteGeometry][B7]**：类型 `#=z1zg8JBfE4I8aYDjrdBvaT3ot4Vlgfodn6sGnL_0FJVXqg7GrYKE8TOs=`；图像 X/Y 缩放 L92–97。
- **B8 — [ManiaNoteBodyStyle 枚举][B8]**：类型 `osu.Graphics.Skinning.ManiaNoteBodyStyle`，L3–9。
- **B9 — [HoldStyle][B9]**：类型 `#=zy_OwNeembJaoOAT5rRJkybFfmkro48YnFSvNa9M=`；头图几何参与身体定位 L540–546；拉伸/重复分支 L562–585。没有在本文扩展其时间算法。
- **B10 — [ScreenGeometry][B10]**：类型 `#=z9cH_AJaI84yk`；逻辑视口宽向上取整 L19–31；过高视口的尺寸限制 L69–77。
- **B11 — [独立算术检查][B11]**：36 个列分配案例和五种比例；仅是对已读公式的复核。
- 主代理已有的 [完整 IL][IL] 只读参考：列宽 5/100 常量及调用在 L1094372–1094387，RVA `0x1f7798`；`SkinMania` 的字段读取方法从 L1094662 开始，RVA `0x1f6ac0`。无需重新输出或修改该文件。
- **T1 — [目前目标导出副本][T1]**：本次只读了解已有导出；其 lazer 专用注释不作为 stable 证据。

[W0]: https://github.com/ppy/osu-wiki/blob/d40667704d4e7f470fea18d882213ac8457bec58/wiki/Skinning/skin.ini/en.md#L156-L188
[W1]: https://github.com/ppy/osu-wiki/blob/c287c6013b9a5e878dfc2c2b9e338322ccd5e1c6/wiki/Skinning/skin.ini/en.md
[W2]: https://github.com/ppy/osu-wiki/blob/c287c6013b9a5e878dfc2c2b9e338322ccd5e1c6/wiki/Skinning/osu!mania/en.md
[W3]: https://github.com/ppy/osu-wiki/blob/c287c6013b9a5e878dfc2c2b9e338322ccd5e1c6/wiki/Skinning/FAQ/en.md
[W4]: https://github.com/ppy/osu-wiki/blob/c287c6013b9a5e878dfc2c2b9e338322ccd5e1c6/wiki/Client/Options/en.md
[W5]: https://github.com/ppy/osu-wiki/blob/c287c6013b9a5e878dfc2c2b9e338322ccd5e1c6/wiki/Client/Keyboard_shortcuts/en.md
[W6]: https://github.com/ppy/osu-wiki/blob/c287c6013b9a5e878dfc2c2b9e338322ccd5e1c6/wiki/Skinning/Interface/en.md
[A1]: https://osu.ppy.sh/beatmapsets/1937932
[L1]: <D:/osu-tools/bad apple mania/osu!Default Skin/skin.ini>
[L2]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/reference-pixels.json
[B1]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/SkinMania.cs
[B2]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/Skin.cs
[B3]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/Section.cs
[B4]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/FloatHelpers.cs
[B5]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/StageLayout.cs
[B6]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/SkinSelection.cs
[B7]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/NoteGeometry.cs
[B8]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/ManiaNoteBodyStyle.cs
[B9]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/HoldStyle.cs
[B10]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/ScreenGeometry.cs
[B11]: D:/osu-tools/osu-paint-stable/build/stable-skin-inspection/arithmetic-checks.json
[IL]: D:/osu-tools/osu-paint-stable/build/stable-inspection/osu.il
[T1]: D:/osu-tools/osu-paint-stable/osu_paint_skin.py
