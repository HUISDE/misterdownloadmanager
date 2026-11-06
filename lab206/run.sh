#!/bin/bash
# #206's measurements and checks on GitHub's runners (never merged: the lab/206-measure branch).
#   run.sh <program> <base|head> <out folder>
# Linux: under Xvfb with Mesa (llvmpipe OpenGL, lavapipe Vulkan: no graphics card); macOS: the
# runner's own session (Metal on Apple's paravirtual GPU). Every run has its own data folder and
# download folder under a temporary one, and is an off-screen test copy (MDM_OFFSCREEN=1) shown at
# 0,0 (MDM_OFFSCREEN_AT) so the screen can be captured.
set -u
app=$1; ref=$2; out=$3
mkdir -p "$out/shots" "$out/logs"
os=$(uname -s)
work=$(mktemp -d)
export MDM_OFFSCREEN=1 MDM_OFFSCREEN_AT=0,0
if [ "$os" = Darwin ]; then gpu=metal; else gpu=vulkan; fi
res="$out/results.txt"
say() { echo "$*" | tee -a "$res"; }

# A fresh data folder with these settings: renderer (JSON: null or "vulkan"…), language, dark.
data_for() {
  local d="$work/$1"; rm -rf "$d"; mkdir -p "$d" "$work/Downloads"
  local dirs=""
  for c in General Compressed Documents Music Programs Video Torrents; do
    local p="$work/Downloads/$c"; [ $c = General ] && p="$work/Downloads"
    dirs="$dirs${dirs:+,}[\"$c\",\"$p\"]"
  done
  cat > "$d/downloads.json" <<J
{"next_id":1,"items":[],"version":2,"settings":{"language":"$3","language_asked":true,"helpers_asked":true,"extension_never_ask":true,"dark_mode_support":$4,"always_dark":$4,"update_check":false,"torrent_incoming":false,"torrent_upnp":false,"torrent_dht":false,"torrent_lsd":false,"renderer":$2,"category_dirs":[$dirs]}}
J
  echo "$d"
}

log_of() { cat "$1"/logs/*.log 2>/dev/null; }
# Wait until the log has `$2` (seconds: $3).
wait_log() {
  for _ in $(seq $(( $3 * 4 ))); do log_of "$1" | grep -q "$2" && return 0; sleep 0.25; done
  return 1
}
pid_of() { pgrep -f "^$app\$" | head -1; }
stop() {
  MDM_DATA_DIR=$1 timeout 10 "$app" /exit >/dev/null 2>&1
  for _ in $(seq 40); do pgrep -f "^$app" >/dev/null || return 0; sleep 0.25; done
  pkill -9 -f "^$app"; sleep 1
}
start() { # data folder, extra env…
  local d=$1; shift
  (cd "$work" && env MDM_DATA_DIR="$d" "$@" "$app" >/dev/null 2>&1 &)
}
keep_log() { cp "$1"/logs/*.log "$out/logs/$2.log" 2>/dev/null; }

# CPU time of a process in clock ticks (Linux) or seconds (macOS, as ps says it).
cpu() {
  if [ "$os" = Darwin ]; then
    ps -o time= -p "$1" | awk -F'[:.]' '{ if (NF==3) print ($1*60+$2)*100+$3; else print ($1*3600+$2*60+$3)*100+$4 }'
  else
    awk '{print $14+$15}' "/proc/$1/stat"
  fi
}
mem() {
  if [ "$os" = Darwin ]; then
    local rss; rss=$(ps -o rss= -p "$1" | tr -d ' ')
    local fp; fp=$(footprint -p "$1" 2>/dev/null | awk '/Footprint/ {print $(NF-1), $NF; exit}')
    [ -z "$fp" ] && fp=$(vmmap --summary "$1" 2>/dev/null | awk '/Physical footprint:/ {print $3; exit}')
    echo "RSS $((rss / 1024)) MB, physical footprint ${fp:-?}"
  else
    awk '/^Rss:/ {r=$2} /^Pss:/ {p=$2} /^Private_Clean:/ {pc=$2} /^Private_Dirty:/ {pd=$2}
      END {printf "RSS %.1f MB, PSS %.1f MB, private %.1f MB", r/1024, p/1024, (pc+pd)/1024}' "/proc/$1/smaps_rollup"
  fi
}
# % of one core over $2 seconds.
idle() {
  local a b; a=$(cpu "$1"); sleep "$2"; b=$(cpu "$1")
  awk -v a="$a" -v b="$b" -v s="$2" 'BEGIN {printf "%.2f %% of one core", (b-a)/s}'
}
shot() { # name: the screen's top-left 1100x700 (the main window opens at 0,0)
  if [ "$os" = Darwin ]; then
    screencapture -x -R 0,0,1100,700 "$out/shots/$1.png" 2>/dev/null || echo "no screencapture: $1"
  else
    import -window root -crop 1100x700+0+0 +repage "$out/shots/$1.png" 2>/dev/null || echo "no import: $1"
  fi
}

# ---- Start-up, idle, memory and the tray, per renderer ---------------------------------------
measure() { # label, renderer JSON, extra env…
  local label=$1 r=$2; shift 2
  local d; d=$(data_for "m-$label" "$r" en false)
  local times=()
  for i in 1 2 3 4 5 6; do
    rm -f "$d"/logs/*.log
    start "$d" "$@"
    if ! wait_log "$d" "first frame drawn" 40; then say "$ref $label: no first frame (run $i)"; keep_log "$d" "$ref-$label-nofirst"; stop "$d"; return; fi
    local ms; ms=$(log_of "$d" | grep -m1 'first frame drawn' | sed -E 's/.*drawn, ([0-9]+) ms.*/\1/')
    # The first run is cold (fonts, the shader cache): kept apart.
    [ $i -gt 1 ] && times+=("$ms")
    [ $i = 1 ] && say "$ref $label: cold start, first frame $ms ms"
    if [ $i -lt 6 ]; then stop "$d"; fi
  done
  local sorted; sorted=$(printf '%s\n' "${times[@]}" | sort -n | tr '\n' ' ')
  local med; med=$(printf '%s\n' "${times[@]}" | sort -n | sed -n 3p)
  say "$ref $label: first frame, 5 warm starts: $sorted(median $med ms)"
  say "$ref $label: $(log_of "$d" | grep -m1 -o 'drawing with [^,]*, [0-9]* ms after start')"
  local pid; pid=$(pid_of)
  sleep 15
  say "$ref $label: window open, idle $(idle "$pid" 30); $(mem "$pid")"
  MDM_DATA_DIR=$d timeout 10 "$app" /show tray >/dev/null 2>&1
  sleep 10
  say "$ref $label: hidden to the tray 10 s: $(mem "$pid")"
  sleep 125
  say "$ref $label: hidden 135 s (after the 2-minute trim): $(mem "$pid"); idle $(idle "$pid" 30)"
  keep_log "$d" "$ref-$label"
  stop "$d"
}

say "== $ref on $os: $("$app" --version 2>/dev/null | head -1)"
measure opengl null
if [ "$ref" = head ]; then
  # The user's choice of the system's API (watched, as a card's start): Mesa's lavapipe taken for
  # a card on Linux (MDM_TEST_SOFTWARE_CARD=1: the runner has none).
  measure "$gpu" "\"$gpu\"" MDM_TEST_SOFTWARE_CARD=1
fi
[ "$ref" = head ] || exit 0

# ---- The fallbacks ---------------------------------------------------------------------------
check() { # name, data folder, what the log must have, what the failure file must start with ("" none)
  local name=$1 d=$2 want=$3 file=$4
  local got; got=$(log_of "$d" | grep -m1 -o 'drawing with [^,]*, [0-9]* ms after start.*' | cut -c1-260)
  local f; f=$(head -1 "$d/$gpu-failed.txt" 2>/dev/null)
  local ok=PASS
  log_of "$d" | grep -q "$want" || ok=FAIL
  [ -n "$file" ] && [ "$f" != "$file" ] && ok=FAIL
  [ -z "$file" ] && [ -n "$f" ] && ok=FAIL
  say "$ok $name: ${got:-no window}; failure file: ${f:-none}"
  keep_log "$d" "fallback-$name"
}
one() { # name, renderer JSON, want, file, extra env…
  local name=$1 r=$2 want=$3 file=$4; shift 4
  local d; d=$(data_for "f-$name" "$r" en false)
  start "$d" "$@"
  wait_log "$d" "first frame drawn" 40
  sleep 1
  check "$name" "$d" "$want" "$file"
  stop "$d"
}
# The choice on a computer without a card's driver: OpenGL, and why.
one no-card "\"$gpu\"" "drawing with OpenGL" no-adapter
# The system's API there, by a card's start (the lab's software renderer taken for one).
one "$gpu-draws" "\"$gpu\"" "drawing with $( [ $gpu = metal ] && echo Metal || echo Vulkan) on" "" MDM_TEST_SOFTWARE_CARD=1
# No driver at all: the Vulkan loader finds none.
[ $gpu = vulkan ] && one no-driver '"vulkan"' "drawing with OpenGL" no-adapter MDM_TEST_SOFTWARE_CARD=1 VK_ICD_FILENAMES=/nonexistent/none.json
# A start with no adapter wanted (the override): OpenGL, nothing remembered.
one override-none null "drawing with OpenGL" "" MDM_RENDERER=$gpu-none
# The software renderer by the override.
one software null "drawing with" "" MDM_RENDERER=software

# The first frame that never comes: MDM starts again with OpenGL within ~10 s.
d=$(data_for f-watchdog "\"$gpu\"" en false)
start "$d" MDM_TEST_SOFTWARE_CARD=1 MDM_TEST_NO_FIRST_FRAME=1
sleep 20
check watchdog "$d" "drew no first frame within 10 s" no-first-frame
log_of "$d" | grep -q "drawing with OpenGL" && say "PASS watchdog: started again with OpenGL" || say "FAIL watchdog: no OpenGL start after it"
# The menu then says why (shot below uses another folder; this one's log is kept).
stop "$d"

# The graphics card lost: MDM starts again with the same API; lost again soon after: OpenGL.
d=$(data_for f-lost "\"$gpu\"" en false)
start "$d" MDM_TEST_SOFTWARE_CARD=1
wait_log "$d" "first frame drawn" 40; sleep 2
MDM_DATA_DIR=$d timeout 10 "$app" /show renderer-lost >/dev/null 2>&1
sleep 12
n=$(log_of "$d" | grep -c "drawing with $( [ $gpu = metal ] && echo Metal || echo Vulkan) on")
say "$( [ "$n" -ge 2 ] && echo PASS || echo FAIL) lost once: started again with $gpu ($n starts with it)"
MDM_DATA_DIR=$d timeout 10 "$app" /show renderer-lost >/dev/null 2>&1
sleep 12
check lost-twice "$d" "twice within 10 minutes" lost-twice
log_of "$d" | tail -1 >/dev/null
stop "$d"

# ---- Screenshots: every language and mode, OpenGL and the system's API, and the menu ----------
for lang in en de ar; do
  for mode in light dark; do
    dark=false; [ $mode = dark ] && dark=true
    for r in opengl "$gpu"; do
      d=$(data_for "s-$lang-$mode-$r" "\"$r\"" $lang $dark)
      start "$d" MDM_TEST_SOFTWARE_CARD=1
      wait_log "$d" "first frame drawn" 40; sleep 3
      shot "main-$lang-$mode-$r"
      MDM_DATA_DIR=$d timeout 10 "$app" /show menu:3:draw >/dev/null 2>&1; sleep 2
      shot "menu-$lang-$mode-$r"
      stop "$d"
    done
    # The note: chosen, but it failed here (no card's driver: the runner has none).
    d=$(data_for "s-$lang-$mode-failed" "\"$gpu\"" $lang $dark)
    start "$d"
    wait_log "$d" "first frame drawn" 40; sleep 3
    MDM_DATA_DIR=$d timeout 10 "$app" /show menu:3:draw >/dev/null 2>&1; sleep 2
    shot "menu-$lang-$mode-failed"
    stop "$d"
  done
done

# No Vulkan loader at all (Linux): removed last, as nothing after needs it.
if [ $gpu = vulkan ]; then
  sudo rm -f /usr/lib/x86_64-linux-gnu/libvulkan.so.1*
  one no-loader '"vulkan"' "drawing with OpenGL" no-adapter MDM_TEST_SOFTWARE_CARD=1
fi
say "== done"
