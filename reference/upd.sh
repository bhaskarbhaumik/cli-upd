#!/usr/bin/env zsh

# ╭───────────────────────────────────────────────────────────────────────╮
# │ Define some global variables...                                       │
# ╰───────────────────────────────────────────────────────────────────────╯
_pgm="${ZSH_ARGZERO:P:t}"
_pgm_dir="${ZSH_ARGZERO:P:h}"
_mod_dir="${_pgm_dir}/upd-modules"
_sudo=/usr/local/sbin/xlog
_rc=0

# ╭───────────────────────────────────────────────────────────────────────╮
# │ Determine exec path and presence of critical files and directories... │
# ╰───────────────────────────────────────────────────────────────────────╯
if [ -r "${_pgm_dir}/upd-functions.sh" ]; then
    source "${_pgm_dir}/upd-functions.sh"
else
    error_exit "upd-functions.sh: missing file"
fi


# ╭───────────────────────────────────────────────────────────────────────╮
# │ Check for critical commands...                                        │
# ╰───────────────────────────────────────────────────────────────────────╯
[ -s "${_sudo}" ] || error_exit "${_sudo}: missing command"
chk_cmd rich
chk_cmd gsed
chk_dir "${_mod_dir}"

# ╭───────────────────────────────────────────────────────────────────────╮
# │ Define update functions...                                            │
# ╰───────────────────────────────────────────────────────────────────────╯
function update_module() {
    mod_file="${_mod_dir}/$1"
    if [ ! -r "${mod_file}" ]; then
        error_exit "$1: no such module."
    fi
    if [ -z "$2" ]; then
        mod_title="Update: $1"
    else
        mod_title="$2"
    fi
    icon=${_package_icon[$1]:-"\ueb29"}
    printf "[${_color[p]}]\uf120[/${_color[p]}]  Starting the update of module [bold white]${icon}[/bold white] [b ${_color[y]}]$1[/b ${_color[y]}]" | \
      rich --emoji -p -a rounded -e -s "${_color[c]}" --title "$(printf ":hourglass: [dim]Started updating module[/dim] [bold white]${icon}[/bold white] [b ${_color[y]}]$1[/b ${_color[y]}] [dim]at :clock1: $(date)[/dim]")" - 2>/dev/null
    chk_file "${mod_file}"
    cat ${mod_file} | \
    rich --emoji -glnL --syntax -x bash -d "1,4,1,4" -a rounded --title "$(echo -en '\uf489') Command(s)" - 2>/dev/null
    rich -uL --rule-style "${_color[g]}" "$(printf "[${_color[g]}]—— \U000f1a9e[/${_color[g]}] [dim]Command Standard Output[/dim]")" 2>/dev/null
    # "${SHELL}" -il "${mod_file}" 2>/tmp/.upd.err
    source "${mod_file}" 2>/tmp/.upd.err
    _rc=$?
    rich -uL --rule-style "${_color[r]}" "$(printf "[${_color[r]}]—— \U000f1aa0[/${_color[r]}] [dim]Command Standard Error[/dim]")" 2>/dev/null
    rich --emoji -glnL --syntax -x text -d "0,2,0,2" -a none "/tmp/.upd.err" 2>/dev/null
    if [ ${_rc} = 0 ]; then
        mark=":white_check_mark:"
        mesg="finished [${_color[g]}]successfully[/${_color[g]}]."
    else
        mark=":cross_mark:"
        mesg="[${_color[r]}]failed[/${_color[r]}] with return code '[${_color[r]}]${_rc}[/${_color[r]}]'."
    fi
    printf "${mark}  Update of module [bold white]${icon}[/bold white] [b ${_color[y]}]$1[/b ${_color[y]}] ${mesg}" | \
      rich --emoji -p -a rounded -e -s "${_color[c]}" --caption "$(printf ":hourglass: [dim]Finished updating module[/dim] [bold white]${icon}[/bold white] [b ${_color[y]}]$1[/b ${_color[y]}] [dim]at :clock5: $(date)[/dim]")" - 2>/dev/null
    echo
}

# ╭───────────────────────────────────────────────────────────────────────╮
# │ M a i n   P r o c e s s i n g . . .                                   │
# ╰───────────────────────────────────────────────────────────────────────╯

if [ "X$1" = "X" ]; then
    # Update all modules...
    # update_module macos    "Upgrade macOS and critical softwares"
    # update_module m365     "Update all Microsoft 365 products"
    # update_module appstore "Update all AppStore apps"
    update_module shellenv "Update Shell Env for zsh"
    update_module brew     "Update Homebrew packages"
    # update_module gcloud   "Update Google Cloud SDK"
    # update_module conda    "Update Conda (Miniconda)"
    # update_module node     "Update Node packages"
    # update_module python   "Update Python 3 packages"
else
    # Update modules supplied in the command line arguments
    while [ ! "X$1" = "X" ]; do
        update_module "$1"
        shift
    done
fi

exit 0

