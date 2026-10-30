; Project-owned minimal AIR input for the real translator FFI test.
target triple = "air64-apple-macosx26.0.0"

define void @increment(ptr addrspace(1) %output, i32 %index) {
entry:
  %address = getelementptr i32, ptr addrspace(1) %output, i32 %index
  %value = add i32 %index, 17
  store i32 %value, ptr addrspace(1) %address, align 4
  ret void
}

!air.kernel = !{!0}
!0 = !{ptr @increment, !1, !2}
!1 = !{}
!2 = !{!3, !4}
!3 = !{i32 0, !"air.buffer", !"air.location_index", i32 0, i32 1, !"air.write", !"air.address_space", i32 1, !"air.arg_type_size", i32 4, !"air.arg_type_align_size", i32 4, !"air.arg_type_name", !"uint", !"air.arg_name", !"output"}
!4 = !{i32 1, !"air.thread_position_in_grid", !"air.arg_type_name", !"uint", !"air.arg_name", !"index"}
