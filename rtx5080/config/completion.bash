# rtx5080 bash completion
# Source this in your .bashrc: source ~/Projects/personal/lario-llms/rtx5080/config/completion.bash

_rtx5080() {
  local cur prev opts models
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"
  opts="vision qwen38 flux sdxl stop status logs switch bench"
  models="vision qwen38 flux sdxl"

  case "${prev}" in
    rtx5080)
      COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
      return 0
      ;;
    switch|logs|bench)
      COMPREPLY=( $(compgen -W "${models}" -- ${cur}) )
      return 0
      ;;
    stop)
      COMPREPLY=( $(compgen -W "${models} all" -- ${cur}) )
      return 0
      ;;
  esac

  COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
}
complete -F _rtx5080 rtx5080