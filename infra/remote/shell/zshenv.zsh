# tau remote access: non-interactive sessions such as `ssh host command` and mosh-server read
# only ~/.zshenv; unless Homebrew and ~/.local/bin enter PATH here, mosh cannot connect.
typeset -U path
path=(/opt/homebrew/bin /opt/homebrew/sbin $HOME/.local/bin $path)
export LANG="${LANG:-en_US.UTF-8}"
# In an SSH session the login keychain may be locked; tokens come from this file when needed (see infra/remote/README.md).
if [[ -n "$SSH_CONNECTION" && -r "$HOME/.config/tau/remote.env" ]]; then
  source "$HOME/.config/tau/remote.env"
fi
