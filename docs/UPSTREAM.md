# 上游研究记录

以下是固定版本研究入口，不构成支持保证。当前通过 upstream/nullarc 子模块接入该提交；已审计首轮提交/等待和队列选择路径，未完成全面安全审计。许可证缺口见 EXPERIMENTAL.md。

## NootedRed
- 仓库：https://github.com/ChefKissInc/NootedRed
- 前序核查提交：`9ff85a6636a3f01d3d1dc02ae09d057605b76c3c`
- 研究入口：`NootedRed/NRed.cpp`、`NootedRed/Kexts.cpp`、`NootedRed/X5000.cpp`。
- 研究目的：设备识别、Apple 驱动补丁组织与分层调试方法；不是已适用于 780M 的实现。
- 不假定其许可证与历史版本相同；任何代码复用前重新读取所选提交的许可证。

## nullarc
- 仓库：https://github.com/luuumi-dev/nullarc
- 前序核查提交：`cbb08ddf517c009255a74ad0fbc2cd7e0d6fa339`
- 前序记录的发行版本：`v0.3.0-alpha`；这里不把它声明为未来的最新版本。
- 研究入口：`README.md`、`docs/INSTALL.md`、`src/phxbringup`、`src/phxaccel`、`src/nmplugin`。
- 候选方向：RDNA3 GPU 初始化、显示/加速接口、RADV 与 Metal 翻译链。
- 上游参考机结果不等于本 ThinkBook 实测；必须核对系统版本、面板、固件和安全设置要求。
- 各组件许可证不同，复用前逐项核查 `LICENSE`、`THIRD_PARTY_NOTICES.md` 及依赖许可证。

## 接入要求
每个引入组件记录上游 URL、提交 SHA/版本、许可证、修改范围和构建方法。
不未经审计运行上游安装脚本，不提交 Apple 系统组件、原始机器固件或未经确认可分发的二进制。

## Metal 插件源码构建
- 编译输入仍是已固定 nullarc 提交中的 `src/nmplugin`；未更新到其他项目的最新实现。
- 编译参数参考 NullMoth 官方 `build/build_plugin_release.sh`，核查提交 `f95f4d24a42f88f9bc71fba12c90bcfe8e060225`。只参考构建参数，未运行其 SSH、安装或复制参考机成品的流程。
- 参考入口：https://github.com/nullmoth/nvidia-macos-driver/blob/f95f4d24a42f88f9bc71fba12c90bcfe8e060225/build/build_plugin_release.sh
- Vulkan-Headers：https://github.com/KhronosGroup/Vulkan-Headers ，固定提交 `6802bb4733b63ed5efd3adb308a6c885ef180ea1`（v1.4.363），许可证按仓库 LICENSE.md 及 LICENSES 中 Apache-2.0/MIT 文本保留。
- 该步骤不提供 RADV、AIR 翻译器或 firmware，不能据此声称完整加速栈已完成。
