/* Compare the actual pinned headers, not a separately retyped ABI. */
#include <stddef.h>
#include "navi48_native_abi.h"
#include "PhxNativeABI.h"

#define CONSTANT(name) _Static_assert(N48N_##name == PHXN_##name, #name)
#define TYPE(name) _Static_assert(sizeof(struct n48n_##name) == sizeof(struct phxn_##name), #name)
#define FIELD(type, field) \
    _Static_assert(offsetof(struct n48n_##type, field) == offsetof(struct phxn_##type, field), #type "." #field); \
    _Static_assert(sizeof(((struct n48n_##type *)0)->field) == sizeof(((struct phxn_##type *)0)->field), #type "." #field " size")

CONSTANT(UC_TYPE);
CONSTANT(ABI_VERSION);
CONSTANT(MAX_IBS);
CONSTANT(MAX_BOS);
CONSTANT(MAX_CTX);
CONSTANT(FENCE_SLOTS);
CONSTANT(WAIT_CAP_NS);
CONSTANT(SEQ_LAST);
CONSTANT(SEL_HELLO);
CONSTANT(SEL_QUERYINFO);
CONSTANT(SEL_READREGS);
CONSTANT(SEL_BOCREATE);
CONSTANT(SEL_BOFREE);
CONSTANT(SEL_GEMVA);
CONSTANT(SEL_CTX);
CONSTANT(SEL_SUBMIT);
CONSTANT(SEL_WAITSEQ);
_Static_assert(N48N_SEL_BO_IMPORT_HOST == PHXN_SEL_BOIMPORTHOST, "host import selector");
_Static_assert(PHXN_ABI_MINOR >= N48N_ABI_MINOR, "kernel minor must cover userspace transport");
TYPE(gem_create_in);
FIELD(gem_create_in, bo_size);
FIELD(gem_create_in, alignment);
FIELD(gem_create_in, domains);
FIELD(gem_create_in, domain_flags);
TYPE(gem_va);
FIELD(gem_va, handle);
FIELD(gem_va, _pad);
FIELD(gem_va, operation);
FIELD(gem_va, flags);
FIELD(gem_va, va_address);
FIELD(gem_va, offset_in_bo);
FIELD(gem_va, map_size);
FIELD(gem_va, vm_timeline_point);
FIELD(gem_va, vm_timeline_syncobj_out);
FIELD(gem_va, num_syncobj_handles);
FIELD(gem_va, input_fence_syncobj_handles);
TYPE(ctx);
FIELD(ctx, op);
FIELD(ctx, flags);
FIELD(ctx, ctx_id);
FIELD(ctx, priority);
TYPE(cs_ib);
FIELD(cs_ib, _pad);
FIELD(cs_ib, flags);
FIELD(cs_ib, va_start);
FIELD(cs_ib, ib_bytes);
FIELD(cs_ib, ip_type);
FIELD(cs_ib, ip_instance);
FIELD(cs_ib, ring);
TYPE(cs_in);
FIELD(cs_in, abi);
FIELD(cs_in, ctx_id);
FIELD(cs_in, num_ibs);
FIELD(cs_in, flags);
FIELD(cs_in, fence_handle);
FIELD(cs_in, fence_offset);
FIELD(cs_in, reserved);
TYPE(info);
FIELD(info, abi_version);
FIELD(info, kext_build);
FIELD(info, flags);
FIELD(info, vmid);
FIELD(info, gb_addr_config);
FIELD(info, gc_version);
FIELD(info, ring_size_dw);
FIELD(info, max_ibs);
FIELD(info, vram_vis_total);
FIELD(info, vram_vis_free);
FIELD(info, vram_hi_total);
FIELD(info, vram_hi_free);
FIELD(info, gtt_cap);
FIELD(info, gtt_used);
FIELD(info, gtt_max_bo);
FIELD(info, pt_cap);
FIELD(info, pt_used);
FIELD(info, seq_emitted);
FIELD(info, seq_retired);
FIELD(info, va_low_first);
FIELD(info, va_low_last);
FIELD(info, va_high_first);
FIELD(info, va_high_last);
FIELD(info, max_bos);
FIELD(info, fence_slots);
FIELD(info, reserved);

int main(void) { return 0; }
