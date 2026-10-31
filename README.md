# Radeon 780M for macOS Tahoe

面向 AMD Radeon 780M 的 macOS Tahoe 实验性驱动适配研发仓库。

> 当前阶段：已接入固定版上游源码和下游内核补丁，建立构建与回归测试。尚无完整安装包或本机 GPU 加速成功的结论。
> 本仓库不是 NootedRed 或 nullarc 官方项目，也不代表与其存在合作关系。

最新完整原生 CI `41175675186`（代码 `ded9914`，包含全部 27 个补丁）已通过：两项 kext、真实 Metal 插件、翻译器、Mesa RADV、LLVM AIR 运行库和 `native-shader-probe` 均完成源码构建、签名及相应检查。该结果只证明 Intel CI 主机上的源码/构建链路，不证明目标笔记本已初始化或获得 GPU 加速；目标机实测仍待完成。
真实插件已加载自带运行库，将两个由 Apple 编译器生成的 metallib 转成不同的、通过校验的 SPIR-V，并通过缺失依赖和损坏输入测试。
以上是非目标 Mac 上的编译链与无设备集成验证：没有创建 Metal/Vulkan 设备或提交 GPU 工作。固件、目标机初始化、内屏与 WindowServer 加速仍未验证，不能直接安装使用。详见 `docs/IMPLEMENTATION-STATUS.md` 与 `docs/validation/ci-298b6fd-full.json`。

## 目标与当前环境
- 首个目标设备也是当前研发笔记本：Lenovo ThinkBook 16 G6+ AHP，Ryzen 7 8845H / Radeon 780M（此前采集 PCI ID：1002:1900）。Windows 上的仓库操作发生在这台机器，但 GPU 实测必须切换到它的 Tahoe 系统后进行。
- 目标系统：macOS Tahoe；具体版本和 build 在切换后实测登记，不预设已经安装。
- 当前已知基线：Sonoma Recovery 可启动，内置键盘与触控板移动/实体点击可用；尚无 GPU 加速证据。
- 目标安装位置：外接 HIKSEMI SSD；不得修改内部 Windows EFI 或分区。

## 研发方向
借鉴 NootedRed 的硬件识别、补丁组织与调试方法；优先评估已有 RDNA3 路线是否适合本机，而不是只修改设备 ID。
已通过固定提交子模块接入 nullarc；完成首轮执行路径审计并加入严格执行补丁。尚未部署驱动或完成全部安全/兼容性审计。
先验证 GPU 初始化和实际命令结果，再推进内屏、Metal 与 WindowServer，最后做稳定性和电源管理。
任何成功状态均须有本机测试证据，不能以显卡名称、显存数字或单个注册表节点作为加速验收。

## 仓库结构
- `docs/ROADMAP.md`：阶段目标和验收条件。
- `docs/UPSTREAM.md`：上游研究入口、版本和许可证边界。
- `docs/NULLMOTH-REFERENCE.md`：NullMoth NVIDIA 项目的架构参考与不可移植边界。
- `upstream/nullarc`：固定提交的上游实现，保留原许可证。
- `patches/`、`src/PhxHardwarePolicy.hpp`：实际内核补丁与共享硬件策略。
- `tools/`、`tests/`：隔离构建、产物校验与真实 Metal 计算探针。
- `tools/target_preflight.py`、`docs/TARGET-PREFLIGHT.md`：从私有目标清单生成仅允许 `--check` 的只读门禁。
- `docs/BUILD.md`、`docs/IMPLEMENTATION-STATUS.md`：构建方法与未完成项。
- `docs/NATIVE-SHADER-PROBE.md`：经原生 GPUVM/BO/提交接口验收着色器的候选探针，尚未实机验证。
- `docs/TARGET-INVENTORY.md`：目标机只读元数据采集；不安装驱动、不提交 GPU 工作，报告仅保存在本地。
- `firmware.lock.json`、`docs/FIRMWARE-MANIFEST.md`：固定官方固件来源和哈希，离线解析文件分段；不包含固件、不加载硬件。
- `AGENTS.md`：隐私、安全、回退和 GitHub 同步要求。

本机 EFI 配置继续由独立私有仓库 `AgnoyZ/thinkbook-16-g6-ahp-hackintosh` 管理，本仓库不替换它。
原始日志、照片、固件转储、个人 EFI 配置、机器唯一标识和 macOS 镜像不得提交。

## 开始实验前
1. 在外接盘完成 Tahoe 安装并确认可稳定启动，记录实际版本/build。
2. 保留工作 EFI、独立救援启动介质以及明确的回退步骤。
3. 完成候选实现的源码、许可证、系统改动与硬件差异审计。
4. 实验驱动不直接替换工作基线；每次只改变一个可验证变量。

没有自动安装脚本，本次初始化不修改任何 EFI、系统安全设置或磁盘。

## 许可证
尚未选择本项目的分发许可证；不因仓库存在而授予第三方代码的再许可权。
引入任何代码、固件或二进制前必须记录来源、固定版本、原许可证及再分发条件。

初始化日期：2026-10-30。
