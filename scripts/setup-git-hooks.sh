#!/bin/bash
# One-time setup for git merge drivers and hooks.
# Run this once per machine after cloning the repo.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Setting up git configuration for frame-art-shuffler..."

# Configure the manifest-version merge driver to use our script
git config merge.manifest-version.name "Always take higher manifest version"
git config merge.manifest-version.driver "$SCRIPT_DIR/git-manifest-merge %O %A %B"

# Make the merge script executable
chmod +x "$SCRIPT_DIR/git-manifest-merge"

echo "✓ Git merge driver configured for manifest.json"
echo ""
echo "Done! When rebasing/merging, manifest.json version conflicts will auto-resolve to the higher version."
