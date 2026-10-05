# Hardware selector completion; choices come from the same registry as the menu.
_lario_hardware_model() {
  local hardware="${COMP_WORDS[0]##*/}" root="${LARIO_LLMS_DIR:-$HOME/Projects/personal/lario-llms}" choices
  choices="$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["models"]))' "$root/$hardware/models.json" 2>/dev/null)" || return
  if [[ ${COMP_WORDS[COMP_CWORD-1]} != switch && ${COMP_WORDS[COMP_CWORD-1]} != warm ]]; then
    choices="$choices list show budget slots reserved context switch warm"
  fi
  mapfile -t COMPREPLY < <(compgen -W "$choices" -- "${COMP_WORDS[COMP_CWORD]}")
}
complete -F _lario_hardware_model geekom 7900xt rtx5080
