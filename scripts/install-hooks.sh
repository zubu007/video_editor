#!/bin/sh
#
# Install the repo's git hooks into .git/hooks/.
#
# Hooks live in scripts/ so they are version-controlled and reviewable; .git/hooks
# is not cloned, so every fresh clone must run this once:
#
#   ./scripts/install-hooks.sh

set -e

repo_root=$(git rev-parse --show-toplevel)
hooks_dir=$(git rev-parse --git-path hooks)

for hook in pre-commit; do
    src="$repo_root/scripts/$hook"
    dest="$hooks_dir/$hook"

    if [ -e "$dest" ] && ! cmp -s "$src" "$dest"; then
        echo "Backing up existing $hook -> $hook.bak"
        cp "$dest" "$dest.bak"
    fi

    cp "$src" "$dest"
    chmod +x "$dest"
    echo "Installed $hook -> $dest"
done

echo "Done. Bypass a single commit with: git commit --no-verify"
