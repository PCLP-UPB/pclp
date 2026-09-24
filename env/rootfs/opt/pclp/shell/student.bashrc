# ~/.bashrc al studentului (setările PCLP sunt în /etc/bash.bashrc -> /opt/pclp/shell/pclp-bash.sh)
case $- in *i*) ;; *) return ;; esac
export EDITOR=nano
# Adaugă aici propriile setări. (Nu redefini PROMPT_COMMAND fără să păstrezi valoarea existentă.)
