#!/bin/sh
# Native read-only capture for Recovery hosts without Python. Keep the entire output private.
PATH=/usr/bin:/bin:/usr/sbin:/sbin
LC_ALL=C
SYSTEM_VERSION_COMPAT=0
unset ENV BASH_ENV CDPATH DYLD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_FRAMEWORK_PATH DYLD_FALLBACK_LIBRARY_PATH
export PATH LC_ALL SYSTEM_VERSION_COMPAT
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }
[ "$#" -eq 1 ] || fail 'Usage: sh recovery_inventory.sh <new-private-output-directory>'
host=$(/usr/bin/uname -s 2>/dev/null) || fail 'Cannot identify the host platform.'
arch=$(/usr/bin/uname -m 2>/dev/null) || fail 'Cannot identify the host architecture.'
[ "$host" = Darwin ] && [ "$arch" = x86_64 ] || fail 'Capture requires Intel macOS or Intel macOS Recovery.'

case "$1" in /*) out=$1 ;; *) out=$PWD/$1 ;; esac
[ ! -e "$out" ] && [ ! -L "$out" ] || fail 'Output already exists; choose a new directory.'
/bin/mkdir "$out" || fail 'Cannot create the private output directory; its parent must exist.'
printf '*\n' > "$out/.gitignore" || fail 'Cannot protect local capture from accidental Git staging.'
printf '%s\n' "$host" > "$out/platform.txt" || fail 'Cannot save platform metadata.'
printf '%s\n' "$arch" > "$out/architecture.txt" || fail 'Cannot save architecture metadata.'

child_pid=
watch_pid=
cleanup() {
    if [ -n "$child_pid" ]; then
        kill -TERM "$child_pid" 2>/dev/null || :
        wait "$child_pid" 2>/dev/null || :
        child_pid=
    fi
    if [ -n "$watch_pid" ]; then
        kill -TERM "$watch_pid" 2>/dev/null || :
        wait "$watch_pid" 2>/dev/null || :
        watch_pid=
    fi
}
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM HUP
trap cleanup 0

run_read() {
    label=$1
    shift
    (
        trap - 0 INT TERM HUP
        # Shell file-size units vary; this restricts each file to at most 16 MiB on supported shells.
        ulimit -f 16384 || exit 70
        exec "$@"
    ) > "$out/$label.txt" 2> "$out/$label.stderr" &
    child_pid=$!
    command_pid=$child_pid
    (
        trap - 0 INT TERM HUP
        sleeper_pid=
        trap 'if [ -n "$sleeper_pid" ]; then kill -TERM "$sleeper_pid" 2>/dev/null || :; wait "$sleeper_pid" 2>/dev/null || :; fi; exit 0' TERM INT HUP
        /bin/sleep 20 &
        sleeper_pid=$!
        wait "$sleeper_pid" || exit 0
        sleeper_pid=
        if [ ! -f "$out/$label.status" ] && kill -0 "$command_pid" 2>/dev/null; then
            : > "$out/$label.timeout"
            kill -TERM "$command_pid" 2>/dev/null || :
        fi
    ) > /dev/null 2>&1 &
    watch_pid=$!
    wait "$child_pid"
    result=$?
    child_pid=
    printf '%s\n' "$result" > "$out/$label.status" || fail 'Cannot save command status.'
    kill -TERM "$watch_pid" 2>/dev/null || :
    wait "$watch_pid" 2>/dev/null || :
    watch_pid=
    [ ! -e "$out/$label.timeout" ] && [ "$result" -eq 0 ] || fail "Metadata command failed or timed out: $label"
    bytes=$(/usr/bin/wc -c < "$out/$label.txt") || fail 'Cannot check capture size.'
    [ "$bytes" -gt 0 ] && [ "$bytes" -le 16777216 ] || fail "Metadata output is empty or exceeds the limit: $label"
}

run_read os_version /usr/bin/sw_vers -productVersion
run_read os_build /usr/bin/sw_vers -buildVersion
run_read darwin_release /usr/sbin/sysctl -n kern.osrelease
run_read ram_bytes /usr/sbin/sysctl -n hw.memsize
run_read pci /usr/sbin/ioreg -a -l -r -c IOPCIDevice -d 1
printf 'PHX780M_NATIVE_CAPTURE_V1\n' > "$out/capture.complete" || fail 'Cannot mark capture completion.'
printf '%s\n' 'Private native capture completed. No GPU work was submitted.'
printf '%s\n' 'Keep the entire directory private; import it with target_inventory.py --from-capture on a Python host.'
