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

## RADV 固定源码与构建接入
- nullarc 的 `docs/architecture-research.md` 明确指向 `Almosst-DEV/Cobalt64`；已解析固定参考提交 `d6c9aedf8e6526a39e349b5886cbc8c7ddf77f65`。
- 该提交的 `mesa-patches/README.txt` 指定 Mesa 基线 `f5cb8ee032adabef599ae892ec4e42d796b84da9`，依次应用九个 Darwin 后端补丁；然后才是 nullarc 的六个 Phoenix 补丁。
- 已核查该 README 和根 LICENSE，补丁声明与 Mesa 同为 MIT。仍需审核具体文件、用户态 ABI 和依赖，不把根许可证视为消除所有来源问题的证明。
- 参考入口：https://github.com/Almosst-DEV/Cobalt64/tree/d6c9aedf8e6526a39e349b5886cbc8c7ddf77f65/mesa-patches
- Mesa 源入口：https://gitlab.freedesktop.org/mesa/mesa.git

- Mesa 基线源码已拉取；九个 Cobalt + 六个 Phoenix 补丁已在独立 worktree 成功应用。工具从固定 Git 对象读取补丁，避免 Windows 换行转换影响应用结果与哈希。
- 新增 downstream 补丁移除 mock 编译单元、拒绝 MOCK/HOST_BO 与非 Phoenix profile、限制服务选择为 PhxBringup；不更改现有 EFI。
- Mesa 的 `docs/license.rst` 明确各文件可能有不同许可证；实际基线使用 `licenses/`，并不存在 Cobalt README 提到的 `third-party/THIRD-PARTY-LICENSES.txt`。构建保留实际许可证目录和 Cobalt 说明，不将 README 的泛称视为全面审计结论。
- 保留上游为 weak entrypoint 使用的 dynamic_lookup 参数，但增加真实 dlopen(RTLD_NOW)、Vulkan 实例创建与无设备枚举测试。此测试不提交 GPU 工作，也不证明 Metal 或桌面加速。

## LLVM AIR 读取库源码接入（原生构建待验证）
- 固定 LLVM 官方 `llvmorg-21.1.8`，tag 对象 `42befb84c672d78de430feb4c96710e6aa4fc774` 指向提交 `2078da43e25a4623cab2d0d60decddf709aaea28`。源码：https://github.com/llvm/llvm-project 。这是本项目选择的可复现依赖，不宣称它等于 nullarc 未标版本的成品库。
- 已核查 `llvm/LICENSE.TXT`、Core/BitReader/IRReader/PassBuilder 头文件及 C API 的 buffer 所有权实现。许可证为 Apache-2.0 WITH LLVM-exception，并保留 legacy 与独立 third-party notices；完整二进制发布审计仍未完成。
- 从官方源码构建独立 dylib，使用实际插件所需的 38 个 LLVM C 符号检查，拒绝依赖构建机 Homebrew 路径。关闭不需要的压缩/编辑/网络库，不拷贝未经固定版本的宿主 dylib。
- 新测试拟使用 Xcode 将项目自有 Metal kernel 编译为真实 AIR，再经新 LLVM reader 和既有 Rust 翻译器输出 SPIR-V；这些代码已接入，但在原生 CI 运行成功前不记作通过。Apple 编译器本身及生成的测试中间文件不会提交或发布。

## RADV 原生验证后的依赖修复
- `a296873` / CI `41063982777` 完成实际 dylib 构建、ABI 布局编译检查及四组无设备加载测试，但 otool 报告显示链接了构建机 Homebrew 的 libSPIRV-Tools.dylib，不能作为可直接部署的成品。
- 固定 Mesa 源码的 `meson.options` 将 spirv-tools 明确列为可选调试 feature（CLC 才强制需要；本构建未启用 CLC）。下游使用 `-Dspirv-tools=disabled` 移除意外运行时链接，同时保留独立 spirv-val 测试，并新增非系统 dylib 依赖拒绝检查。修复本身仍需新的原生 CI 验证。

## GFX11 派发探针的测试着色器
- 补丁 0025 从官方 libdrm 2.4.123 源码归档的 `tests/amdgpu/shader_code_gfx11.h` 复用 79 个缓冲区清零着色器指令字，保留完整 AMD 2022 MIT 风格许可和免责说明，仅修改本地符号名；不复制固件或驱动二进制。
- 已核对该数组文件许可，记录归档、参考文件和指令流哈希。派发状态与描述符参考同版 `shader_test_util.c`，缓存包参考固定 Mesa 源；包构造独立实现，不复制这些实现函数。详见 `validation/libdrm-2.4.123-shader-reference.json` 和 `GFX11-SHADER-PROBE.md`。
- 该许可核查仅覆盖本次新增着色器源码，不代表整个驱动栈的公开二进制发布审计已完成；实机执行仍未验证。
