# tau uzaktan erişim: `ssh host komut` ve mosh-server gibi etkileşimsiz oturumlar sadece
# ~/.zshenv okur; Homebrew ve ~/.local/bin burada PATH'e girmezse mosh bağlanamaz.
typeset -U path
path=(/opt/homebrew/bin /opt/homebrew/sbin $HOME/.local/bin $path)
export LANG="${LANG:-en_US.UTF-8}"
# SSH oturumunda login keychain kilitli olabilir; gerekirse token'lar buradan gelir (bkz. infra/remote/README.md).
if [[ -n "$SSH_CONNECTION" && -r "$HOME/.config/tau/remote.env" ]]; then
  source "$HOME/.config/tau/remote.env"
fi
