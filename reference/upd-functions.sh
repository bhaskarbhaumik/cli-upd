#!/usr/bin/env zsh

declare -A _error_level=([t]="trace" [d]="debug" [i]="info" [w]="warning" [e]="error" [f]="fatal")
declare -A _error_icon=([t]="\033[35m\uebd0\033[0m" [d]="\033[34m\uf188\033[0m" [i]="\033[32m\uf05a\033[0m" [w]="\033[33m\uf071\033[0m" [e]="\033[31m\uf071\033[0m" [f]="\033[31m\uf1e2\033[0m")
declare -A _package_icon=([macos]="\U000f01c4" [m365]="\uf17a" [appstore]="\ue713" [gcloud]="\ue7b2" [brew]="\uf0fc" [node]="\U000f0399" [python]=":snake:")
declare -A _color=([p]="#ff33ff" [y]="#ffff00" [c]="#00ccff" [r]="#ff3333" [g]="#00ff66")
declare -A _style=([header]="white on #224422" [rule]="#669966")

# ╭───────────────────────────────────────────────────────────────────────╮
# │ Define utility functions...                                           │
# ╰───────────────────────────────────────────────────────────────────────╯
function error_message() {
    error_level=${1:0:1:l}; shift
    echo -e "${_error_icon[${error_level}]} \033[1;37m${_error_level[${error_level}]}\033[0m: $@" >&2
}

function trace() { error_message t "$@" }
function debug() { error_message d "$@" }
function info()  { error_message i "$@" }
function warn()  { error_message w "$@" }
function error() { error_message e "$@" }
function fatal() { error_message f "$@" }
function error_exit() { error_message e "$@"; exit ${_rc} }
function chk_cmd()    { command -v "$1" &>/dev/null || error_exit "$1: command not found"; return 0 }
function chk_dir()    { test -d "$1" &>/dev/null || error_exit "$1: directory not found"; return 0 }
function chk_file()   { test -f "$1" &>/dev/null || error_exit "$1: file not found"; return 0 }


# ╭───────────────────────────────────────────────────────────────────────╮
# │ Define rich output functions...                                       │
# ╰───────────────────────────────────────────────────────────────────────╯
function print_rule() {
    if [ "X$1" = "X" ]; then
        rich -uL --rule-style "${_style[rule]}"
    else
        title=$(printf "[${_style[rule]}]—— $@")
        rich -uL --rule-style "${_style[rule]}" "${title}"
    fi
}

function print_header() {
    printf "$@" | rich -pj -a rounded -e -s "${_style[header]}" -S "dim ${_style[header]}" -
}
