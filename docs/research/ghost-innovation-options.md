# 残影后续方向：原理与停止条件

核查：2026-10-07。当前同时支持 lazer 2026.921.0 / stable；旧记录“仅 lazer”不是现状。以下三项均尚未实现，只是迁移设想，不宣称个人算法原创、实机收益或零残影；不涉及静帧复用分组。

## 1. 时域／蓝噪声启发的错相（尚未实现）

NVIDIA 的 STBN 用时空蓝噪声改善随机渲染采样[1]，不是现成 osu 解决方案。设想借鉴“减少时间聚集”，在节奏约束下打散连续命中过渡；蓝噪声偏移不保证命中序列也呈蓝噪声，更不等于缩短过渡或降低平均暴露。

- **验证**：固定内容和过渡预算，双端按各自时间精度重解析 `.osu`，覆盖全部相位区间，比较最长连续命中、平均／最坏总命中与帧节奏。
- **停止**：节奏或最坏命中恶化，或多种合成序列没有稳定收益。

## 2. 外部测量后自动校相（尚未实现）

NVIDIA 介绍了高速拍屏与光学传感测端到端延迟[2]，不是 osu 自动校相实现。Hz 只给周期，不能确定相位。设想用外部高速相机拍合成时标，本地自动拟合谱面到出光的有效相位及漂移；软件录屏不能替代物理出光测量。不新增手动相位控件，不移动音轨。

- **验证**：校准／验证片段分离，多次启动复测；检查曝光、相机与屏幕扫描混叠[3]及屏幕上中下差异。
- **停止**：测量误差与漂移超过安全余量、重启不可复现或配置改变，即弃用校准。相机精度是否足够、能否跨播放稳定校准仍未知。

## 3. 黑帧、空场桥接与背光闪烁（尚未实现）

逻辑空场是撤去音符：黑块消失可能露出白底，不是灭光。空场桥接仅作为隔开旧新画面的候选，可能换来亮闪、缺画和额外过渡；全黑图也不等于 LCD 关背光。

一内容帧配一黑帧的 BFI，在固定 Hz 下使有效内容帧率上限为 Hz/2；同峰值亮度下平均亮度下降[4]。LCD 背光闪烁针对保持型运动模糊，在刷新间灭灯，不必占用整张内容帧，但有亮度与频闪代价[5]；推断：灭光窗口未覆盖过渡，就不能遮住混帧，也不能补回低 FPS 视频的信息。刷新率、FPS 与 VRR 兼容依型号；ZOWIE 对部分机型建议超过 100 Hz 且稳定超过 100 FPS[6]，不是通用门槛。

- **验证**：同合成素材分别比较空场、黑帧与背光，测出光、亮度、重复像和帧节奏。
- **停止**：频闪／不适、亮度不足、重复像增加或硬件／FPS 不满足；不默认启用。

## 一手资料

1. NVIDIA：[STBN 论文（2022）](https://research.nvidia.com/publication/2022-07_spatiotemporal-blue-noise-masks)、[作者技术说明](https://developer.nvidia.com/blog/rendering-in-real-time-with-spatiotemporal-blue-noise-textures-part-1/)。
2. NVIDIA：[高速相机与 LDAT 测量](https://www.nvidia.com/en-us/geforce/news/nvidia-reviewer-toolkit/)。
3. ZOWIE：[拍屏频闪与扫描频率差异](https://zowie.benq.eu/en-eu/support/faq/product/explanation/zowiemonitor-faq-kn-00001.html)。
4. ASUS：[运动清晰度与 BFI 代价（2026-02-27）](https://edgeup.asus.com/2026/motion-clarity-what-it-is-why-it-matters-and-how-to-pick-the-right-gaming-monitor-for-your-setup/)。
5. ASUS：[ELMB／ELMB Sync 原理与限制](https://www.asus.com/support/faq/1045888/)。
6. ZOWIE：[DyAc 的刷新率／帧率适用条件](https://zowie.benq.com/en-us/support/faq/product/application/zowiemonitor-faq-kn-00006.html)。
