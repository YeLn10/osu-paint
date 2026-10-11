# 研究与验证索引

[项目首页](../../README.md) · [当前架构](../architecture.md) · [当前时间模型](../timing.md) · [当前皮肤](../skin.md)

这里保存按日期与目标客户端版本记录的调查、实验、失败候选和实机反馈。实现规则以当前技术文档及源码为准；历史记录中的旧参数、阶段测试数量和缓存路径不代表当前配置。

## 客户端与模型依据

| 问题 | 记录 |
| --- | --- |
| 红线、绿线、参考 BPM 与最初的动画模型 | [mania SV 调查](mania-sv-animation.md) |
| 显示相位、底边锚点、长条与空白帧漂移 | [刷新约束与反例](render-phase-constraints.md) |
| stable 整数端点、参考 BPM 与滚速公式 | [stable 时间证据](stable-timing.md) |
| stable 字段类型、列宽、1K 加载与原生解析 | [stable 皮肤证据](stable-skin-evidence.md) |
| lazer 音乐继续但画面定格、AT 频闪反馈 | [时钟定格诊断](lazer-clock-freeze.md) |

## 已实现优化及对照

| 主题 | 记录 |
| --- | --- |
| 实际端点清场、静态复用、留白行程和慢控制点 | [合并后切帧优化](merged-transition-optimization.md) |
| 同组数均衡静帧，缩短总过渡 | [均衡复用](balanced-reuse-optimization.md) |
| 按实际重绘分散固定相位命中，回收排帧余量 | [相位优化](ghost-phase-optimization.md) |
| 有限步长候选减少连续命中 | [连续命中优化](ghost-streak-optimization.md) |
| stable 长清场扩大排帧范围 | [扫屏复核](stable-sweep-optimization.md) |
| stable 按整数帧间隔继续分散长清场 | [整数节奏优化](stable-cadence-optimization.md) |
| stable 原生移动白缝与固定底部遮挡 | [白缝修复](stable-white-seam.md) |

## 探索与证据边界

[后续方向](ghost-innovation-options.md) 区分已落地的有约束折返候选，以及尚未实现的测相位、黑帧和物理显示方案，不构成当前功能承诺。

这些材料分别使用源码核查、目标程序集探测、合成序列化回归或用户实机反馈。清场变短、命中分散、软件采样纯黑，都不能直接推导出 GPU 实机零残影；Hz 也不能确定实际显示相位。

记录中的 `build/` 和 `output/` 路径是历史诊断产物，可能已清理，不是源码运行依赖。可提交的合成基线保存在 `tests/fixtures/`；个人媒体、游戏程序集与凭据不进入仓库。版本功能摘要统一见 [更新日志](../../CHANGELOG.md)，不在架构文档追加交付流水账。
