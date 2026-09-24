# PCLP — configurare bash interactiv: istoric cu timestamp + jurnal de comenzi.
# Jurnal: ~/work/.pclp/terminal.log, o linie TSV per comandă:
#   <ISO8601>\t<cwd (relativ la ~)>\t<cod ieșire>\t<comanda>
# Se înregistrează DOAR comanda (textul tastat), codul de ieșire și directorul — nu și ieșirea ei.

case $- in *i*) ;; *) return ;; esac
[ -n "${__PCLP_BASH_LOADED:-}" ] && return
__PCLP_BASH_LOADED=1

case ":$PATH:" in *:/opt/pclp/wrap:*) ;; *) PATH="/opt/pclp/wrap:/opt/pclp/bin:$PATH" ;; esac

__pclp_work=${PCLP_WORK:-$HOME/work}
HISTTIMEFORMAT='%F %T  '
HISTSIZE=10000
HISTFILESIZE=20000
HISTCONTROL=
if [ -d "$__pclp_work/.pclp/state" ] && [ -w "$__pclp_work/.pclp/state" ]; then
    HISTFILE="$__pclp_work/.pclp/state/bash_history"
fi
shopt -s histappend cmdhist 2>/dev/null

__pclp_last_hist=
__pclp_prompt_hook() {
    local ec=$?
    # VS Code shell integration poate rula înaintea noastră; folosim codul salvat de el dacă există.
    [ -n "${__vsc_status:-}" ] && ec=$__vsc_status
    local line num cmd log="$__pclp_work/.pclp/terminal.log"
    HISTCONTROL=   # altfel comenzile repetate nu ar primi număr nou în istoric
    line=$(HISTTIMEFORMAT= builtin history 1)
    if ! [[ $line =~ ^[[:space:]]*([0-9]+)[\*[:space:]][[:space:]]?(.*)$ ]]; then
        [ -z "$__pclp_last_hist" ] && __pclp_last_hist=0   # istoric gol la pornire
        return $ec
    fi
    num=${BASH_REMATCH[1]}
    cmd=${BASH_REMATCH[2]}
    if [ -z "$__pclp_last_hist" ]; then   # primul prompt: nu reînregistra ultima comandă din fișier
        __pclp_last_hist=$num
        return $ec
    fi
    [ "$num" = "$__pclp_last_hist" ] && return $ec   # Enter pe linie goală
    __pclp_last_hist=$num
    [ -d "$__pclp_work/.pclp" ] || return $ec
    builtin history -a 2>/dev/null
    local cwd=$PWD
    case "$cwd" in "$HOME"/*) cwd="~/${cwd#"$HOME"/}" ;; "$HOME") cwd="~" ;; esac
    cmd=${cmd//$'\t'/ }
    cmd=${cmd//$'\n'/ ⏎ }
    printf '%s\t%s\t%s\t%s\n' "$(date +%Y-%m-%dT%H:%M:%S%:z)" "$cwd" "$ec" "$cmd" >>"$log" 2>/dev/null
    return $ec
}

# Hook-ul nostru rulează PRIMUL, ca $? să fie codul comenzii; păstrăm PROMPT_COMMAND existent.
if [[ "$(declare -p PROMPT_COMMAND 2>/dev/null)" == "declare -a"* ]]; then
    PROMPT_COMMAND=(__pclp_prompt_hook "${PROMPT_COMMAND[@]}")
else
    PROMPT_COMMAND="__pclp_prompt_hook${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi

# Prompt colorat: [pclp] ~/work/sapt-01/problema $
__pclp_ps1_status() { local e=$?; [ $e -ne 0 ] && printf '\001\033[1;31m\002[%d] ' "$e"; return $e; }
PS1='$(__pclp_ps1_status)\[\033[1;32m\]\u@pclp\[\033[0m\]:\[\033[1;34m\]\w\[\033[0m\]\$ '

alias ls='ls --color=auto'
alias ll='ls -alF --color=auto'
alias grep='grep --color=auto'
[ -r /usr/share/bash-completion/bash_completion ] && . /usr/share/bash-completion/bash_completion

# Reamintire: identitatea studentului lipsește
if [ -f "$__pclp_work/.pclp/student.json" ] && grep -q '"name": ""' "$__pclp_work/.pclp/student.json" 2>/dev/null; then
    printf '\033[1;33mPCLP: rulează `pclp init` ca să îți completezi numele, emailul Moodle și grupa.\033[0m\n'
fi
