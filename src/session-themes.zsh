# Loaded by the labelled block in ~/.zshrc. Settings: session-themes.conf.
[[ -o interactive ]] || return 0

typeset -g _ghostty_session_theme_directory="${${(%):-%x}:A:h}"

function session-theme() {
    emulate -L zsh
    local result
    if [[ ${1:-} == reload ]]; then
        "$_ghostty_session_theme_directory/session-theme" _init
    else
        "$_ghostty_session_theme_directory/session-theme" "$@"
    fi
    result=$?
    if (( result == 0 )); then
        typeset -g _ghostty_session_theme_paused=0
    fi
    return $result
}

function _ghostty_session_theme_precmd() {
    emulate -L zsh
    [[ ${_ghostty_session_theme_paused:-0} == 0 && -t 0 && -t 1 ]] || return 0
    "$_ghostty_session_theme_directory/session-theme" _sync || {
        typeset -g _ghostty_session_theme_paused=1
    }
    return 0
}

# Only direct local Ghostty terminals get automatic colours. A nested shell
# on the same TTY inherits the session ID; a new terminal gets its own ID.
if [[ $TERM_PROGRAM == ghostty && -z $SSH_CONNECTION && -z $TMUX && -z $STY && -t 0 && -t 1 ]]; then
    if [[ ${GHOSTTY_SESSION_THEME_TTY:-} != $TTY || -z ${GHOSTTY_SESSION_THEME_ID:-} ]]; then
        export GHOSTTY_SESSION_THEME_TTY="$TTY"
        export GHOSTTY_SESSION_THEME_ID="$(/usr/bin/uuidgen)"
    fi
    typeset -g _ghostty_session_theme_paused=0
    "$_ghostty_session_theme_directory/session-theme" _init || {
        typeset -g _ghostty_session_theme_paused=1
    }
    autoload -Uz add-zsh-hook
    add-zsh-hook -d precmd _ghostty_session_theme_precmd
    add-zsh-hook precmd _ghostty_session_theme_precmd
fi
