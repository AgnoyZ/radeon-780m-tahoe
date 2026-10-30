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

## AIR 翻译器接入
- 使用 nullarc v0.3.0-alpha 附带的 `nvmtl-translator-source.tar.gz`，不是可变的上游 main，也不是已编译 dylib。
- 固定 SHA-256：`1252d982578b19e18144266aab994bb354a757c7491dcb33c15518b6791c3f3c`；源 URL、根目录与 Rust 工具链记在 upstream.lock.json。
- 已核查归档 NOTICE、translator/LICENSE、translator/COPYING 和 wrapper/Cargo.lock。NOTICE 声明 metal2vulkan 及 NullMoth 修改为 LGPL-3.0-or-later。
- 源码未修改；单独动态链接，构建保留相应源归档和许可证。API 按固定插件实际 dlsym 的 16 个符号逐一检查。
- 这不提供 RADV、LLVM AIR 读取库、硬件 firmware 或自动启动服务，也不等于实机 Metal 加速。

## 下一步 RADV 的已核查源码入口（尚未接入构建）
- nullarc 的 `docs/architecture-research.md` 明确指向 `Almosst-DEV/Cobalt64`；已解析固定参考提交 `d6c9aedf8e6526a39e349b5886cbc8c7ddf77f65`。
- 该提交的 `mesa-patches/README.txt` 指定 Mesa 基线 `f5cb8ee032adabef599ae892ec4e42d796b84da9`，依次应用九个 Darwin 后端补丁；然后才是 nullarc 的六个 Phoenix 补丁。
- 已核查该 README 和根 LICENSE，补丁声明与 Mesa 同为 MIT。仍需审核具体文件、用户态 ABI 和依赖，不把根许可证视为消除所有来源问题的证明。
- 参考入口：https://github.com/Almosst-DEV/Cobalt64/tree/d6c9aedf8e6526a39e349b5886cbc8c7ddf77f65/mesa-patches
- Mesa 源入口：https://gitlab.freedesktop.org/mesa/mesa.git
