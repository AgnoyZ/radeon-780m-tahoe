# NullMoth NVIDIA 项目参考边界

本项目已审阅 `nullmoth/nvidia-macos-driver` 的公开主分支提交
`ceba63c15ba9d81deea7cd1c5dcc4c79497bea8f`（2026-10-31）。它可以作为
macOS 第三方 GPU 驱动的**架构和验证流程参考**，不能作为 Radeon 780M
驱动的可直接移植代码包。

## 可以借鉴的结构

NullMoth 项目把驱动拆成几个可独立验证的层：

```text
Metal 插件 -> AIR/SPIR-V 翻译 -> Mesa Vulkan 后端 -> 内核资源管理
          -> framebuffer / accelerator / 显示策略 -> GPU
```

对本项目有价值的做法包括：

- 将 Metal 插件、翻译器、Mesa 后端、内核资源管理和显示输出分层，分别做构建和负向测试；
- 在驱动安装前做依赖、签名、设备身份和配置备份检查；
- 为无法启动的情况提供明确的禁用/卸载回退入口；
- 让插件只加载自身旁边的运行库，避免依赖构建机路径或环境变量；
- 先验证无设备/拒绝路径，再进行真实设备测试；
- 把 framebuffer、accelerator、显示策略和 Metal 设备验收分开，不把“设备名称出现”当作加速成功。

本仓库已经对应实现了其中一部分：`PhxBringup.kext`、`PhxAccel.kext`、RADV、AIR
运行库、Metal 插件、原生 GPUVM 探针、目标清单和只读 preflight 门禁。

## 不能直接复用的部分

| NullMoth NVIDIA | 本 Radeon 780M 项目 | 不能直接替换的原因 |
| --- | --- | --- |
| NVIDIA open GPU kernel modules / GSP | AMD PSP、MES、GART、GPUVM、SDMA/GC 固件 | 固件协议、寄存器、队列、内存模型和完成语义完全不同 |
| NVK + NAK | Mesa RADV + AMD GFX11 shader/命令路径 | 编译器、命令包、资源描述符和 GPU ISA 不同 |
| NVRMFB / NVAccel / NVRMAGDC | Phx framebuffer / accelerator 路径 | IOGraphics 接口可类比，硬件实现和所有权协议不能照搬 |
| BAR1 显存窗口和离散显卡 VRAM | 780M UMA/GTT 与系统内存 | 不能复制 BAR 大小、VRAM 地址或显示保留区 |
| `nvfb`、`nvaccel` 等 boot-args | 本项目的 `phx780m=1` 研究门禁 | 参数名和开关语义不是跨厂商 ABI |
| NVIDIA GSP 固件 | AMD 官方固件组件 | 许可证、版本匹配和加载协议不同，不能混用 |

特别禁止把 NullMoth 文档中的 BAR、`ResizeGpuBars`、SMBIOS、boot-args、kext
路径或固件地址复制到本机。它们是 NVIDIA/离散显卡测试环境的条件，不是
ThinkBook 780M 的结论。

## 对本项目的具体影响

NullMoth 的分层设计说明本项目的 Metal 方向是合理的，但它不能替代最关键的
AMD 真机工作：

1. 从 Tahoe 目标机采集实际 Darwin build、PCI 资源、GPU IP、UMA 保留和固件状态；
2. 独立确认 PSP/MES/GART 的目标内存所有权和队列所有权；
3. 先执行 `native-shader-probe --check`，再在人工审核后执行真实 GPUVM 探针；
4. 获得正确的 GPU 写入结果和退休同步后，才继续 framebuffer、Metal 和 WindowServer；
5. 每一层都要有失败回退，不把实验 kext 自动写入工作 EFI。

因此结论是：**可以参照 NullMoth 的分层架构、测试隔离和回退设计；不能
参照其 NVIDIA 内核代码、寄存器/固件流程或安装参数来直接实现 Radeon 780M。**

## 许可证与来源

审阅来源：

- https://github.com/nullmoth/nvidia-macos-driver/tree/ceba63c15ba9d81deea7cd1c5dcc4c79497bea8f
- 该提交的仓库 `LICENSE` 为 PolyForm Noncommercial 1.0.0，仓库还包含 LGPL
  翻译器、Mesa 和 NVIDIA 固件等不同来源；不能因“参考”而推断代码或二进制可再分发。
- 本文件只记录架构比较，没有复制 NullMoth 源代码、固件或二进制。
