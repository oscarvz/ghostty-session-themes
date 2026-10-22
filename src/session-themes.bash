# Loaded by the managed startup block. Compatible with Bash 3.2 and newer.
[[ $- == *i* ]] || return 0

_ghostty_session_theme_directory="$(cd -P -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

function session-theme() {
    local result
    if [[ ${1:-} == reload ]]; then
        "$_ghostty_session_theme_directory/session-theme" _init
    else
        "$_ghostty_session_theme_directory/session-theme" "$@"
    fi
    result=$?
    if (( result == 0 )); then
        _ghostty_session_theme_paused=0
    fi
    return "$result"
}

_ghostty_session_theme_precmd() {
    local result=$?
    if [[ ${_ghostty_session_theme_paused:-0} == 0 && -t 0 && -t 1 ]]; then
        "$_ghostty_session_theme_directory/session-theme" _sync || _ghostty_session_theme_paused=1
    fi
    return "$result"
}

# Only direct, local Ghostty terminals participate. Both hooks share the same
# exported identity so switching between Bash and zsh keeps the current family.
if [[ ${TERM_PROGRAM:-} == ghostty && -z ${SSH_CONNECTION:-} && -z ${TMUX:-} && -z ${STY:-} && -t 0 && -t 1 ]]; then
    _ghostty_session_theme_tty="$(tty)"
    if [[ ${GHOSTTY_SESSION_THEME_TTY:-} != "$_ghostty_session_theme_tty" || -z ${GHOSTTY_SESSION_THEME_ID:-} ]]; then
        export GHOSTTY_SESSION_THEME_TTY="$_ghostty_session_theme_tty"
        export GHOSTTY_SESSION_THEME_ID="$("$_ghostty_session_theme_directory/session-theme" _uuid)"
    fi
    _ghostty_session_theme_paused=0
    "$_ghostty_session_theme_directory/session-theme" _init || _ghostty_session_theme_paused=1

    # Preserve existing callbacks and their order, including Ghostty's own hook.
    if [[ $(declare -p PROMPT_COMMAND 2>/dev/null) == 'declare -a '* ]]; then
        _ghostty_session_theme_registered=0
        for _ghostty_session_theme_callback in "${PROMPT_COMMAND[@]}"; do
            if [[ $_ghostty_session_theme_callback == _ghostty_session_theme_precmd ]]; then
                _ghostty_session_theme_registered=1
            fi
        done
        if [[ $_ghostty_session_theme_registered == 0 ]]; then
            PROMPT_COMMAND+=(_ghostty_session_theme_precmd)
        fi
    elif [[ ${PROMPT_COMMAND:-} != *'_ghostty_session_theme_precmd'* ]]; then
        # A newline also handles an existing command ending with a comment.
        PROMPT_COMMAND="${PROMPT_COMMAND:+${PROMPT_COMMAND}$'\n'}_ghostty_session_theme_precmd"
    fi
fi
