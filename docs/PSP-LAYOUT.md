# Explicit PSP layout: numeric contract, not a memory reservation

Patch `0009-explicit-psp-layout.patch` removes the managed kernel PSP path's
implicit TMR and firmware-buffer offsets. A driver instance starts without a
configured layout. Creating a PSP ring requires an explicit versioned descriptor;
the ring offset in the create request must match it. No target profile or default
addresses are supplied by this project.

This is a prerequisite for target initialization, not an installation procedure.
It does **not** determine which target memory is free, reserve pages, exclude the
console or firmware allocations, authenticate a hardware discovery result, or
prove the PSP's address interpretation. Do not run it against the working EFI.

## Shared wire contract and checks

`src/PhxPspLayout.h` is copied into the staged kernel source and included by the
actual `phxctl`. The 64-byte descriptor contains eight unsigned 64-bit words:

| Word | Meaning |
| --- | --- |
| 0 | Contract version, currently 1 |
| 1 | Ring region offset from the VRAM base |
| 2 | TMR region offset |
| 3 | TMR capacity in bytes |
| 4 | Firmware staging region offset |
| 5 | Firmware staging capacity in bytes |
| 6-7 | Reserved, must be zero |

The ring region covers the existing ring/command/fence layout through the end of
the fence page (36 KiB). All region offsets and capacities must be page-aligned;
capacities must be positive. TMR size must fit the existing 32-bit command field.
The staging capacity remains capped at the control tool's 16 MiB snapshot limit.
These are implementation bounds, not a claim that page alignment alone satisfies
all target firmware requirements.

The shared validator requires every region to fit **both** the reported VRAM
extent and the mapped BAR0 aperture. It rejects pairwise overlap without computing
overflowing ends. It also validates nonzero/page-aligned MC and physical bases,
and that the complete reported VRAM span is representable at each base. BAR0's
CPU physical base is not substituted for the backing VRAM physical base.

Selector 114 takes this structure and returns four scalar observations on success:
MC base, backing physical base, VRAM size and mapped aperture size. The existing
HELLO, debug-enable and privileged-client checks remain mandatory. Configuring
the layout only stores software metadata: it does not access aperture contents,
submit PSP commands or write registers. A faulted PSP instance or a live
ring/TMR/staging state or adopted GPU queue rejects reconfiguration. Invalid
configuration leaves any previously accepted descriptor unchanged.

Ring creation repeats the full numeric validation under the PSP lock immediately
before touching memory. A missing descriptor, changed bounds or mismatching ring
offset stops before register or aperture access. After successful creation, TMR
and staging addresses/capacities come from the descriptor. `SETUP_TMR` now requires
an explicit nonzero requested size within its configured capacity; the former
implicit 4 MiB request and fixed 16 MiB TMR cap are no longer used.

## Control interface and compatibility

The research CLI's syntax is:

```text
phxctl psp-layout <ring-offset> <tmr-offset> <tmr-capacity> <staging-offset> <staging-capacity>
```

Offsets are relative to VRAM, not physical or MC addresses. All five fields use
checked unsigned 64-bit parsing. This command only configures metadata and reports
numeric acceptance; it does not create a ring, load firmware or prove ownership.
Transport failure or a short/long reply is terminal. The supplied memory ranges
must ultimately come from a reviewed allocation/reservation mechanism, which is
not implemented yet. No example target addresses are provided as defaults.

Older scripts that directly create a ring or omit a TMR size now fail. An older
kernel without selector 114 also rejects the new configuration request. Existing
RADV selectors and structure sizes are unchanged. The raw-debug command paths
remain research interfaces outside this managed layout contract; they are not
safe orchestration shortcuts.

## Verification and remaining work

The actual-method PSP harness now includes `configurePspLayout` along with the
previous six kernel methods. Its 48 cases include successful configuration and
ring creation using deliberately different synthetic offsets, unchanged memory
on precondition failure, overlap, aperture/VRAM bounds, address overflow,
reconfiguration refusal and zero TMR-size rejection. It checks the resulting
ring/command/fence/TMR/staging addresses and exactly which fake memory words were
cleared. The shared header also has arithmetic boundary/exhaustive disjointness
checks in the C++ policy suite.

The actual CLI harness now has 46 cases, including seven layout transport and
argument cases. It verifies the 64-byte descriptor and zero firmware-stage/load
calls during configuration. All native C/C++ execution for this new revision is
pending CI; 106 Python source/runner tests passed locally. A fake-memory ring
creation is not hardware execution, and a successful source build will not prove
target firmware compatibility.

Target Tahoe inventory and reserved-region ownership are still missing. The
broader `mesboot.c` GART/queue/default-page addresses remain reference constants.
The next integration must connect this interface to actual reserved regions,
firmware selection and a checked initialization sequence before target execution.
There is no new automatic reset, rollback, security change or EFI deployment.
