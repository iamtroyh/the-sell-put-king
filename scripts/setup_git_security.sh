#!/usr/bin/env bash
# ==============================================================================
# Setup Git Security Hooks & Pre-Commit Safeguards for Quant Option Project
# ==============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

if [ ! -d "$PROJECT_ROOT/.git" ]; then
    echo "⚙️ Initializing Git repository..."
    git init "$PROJECT_ROOT"
fi

mkdir -p "$HOOKS_DIR"

PRE_COMMIT_HOOK="$HOOKS_DIR/pre-commit"

cat << 'EOF' > "$PRE_COMMIT_HOOK"
#!/usr/bin/env bash
# Pre-commit hook to prevent committing sensitive keys or credentials files

echo "🔍 Running Git Pre-Commit Security Checks..."

# Check 1: Block credentials.json
if git diff --cached --name-only | grep -E '^config/credentials\.json$' > /dev/null; then
    echo "❌ [SECURITY ERROR] Attempting to commit config/credentials.json!"
    echo "Please remove it from staging: git reset HEAD config/credentials.json"
    exit 1
fi

# Check 2: Block dynamic private data files
if git diff --cached --name-only | grep -E '^data/.*\.json$' > /dev/null; then
    echo "❌ [SECURITY ERROR] Attempting to commit private data JSON files in data/!"
    echo "Please unstage data files before committing."
    exit 1
fi

# Check 3: Scan staged diff for potential account ID leak
STAGED_DIFF=$(git diff --cached)
if echo "$STAGED_DIFF" | grep -E '[0-9]{12}' > /dev/null; then
    echo "⚠️ [SECURITY WARNING] Staged diff contains a 12-digit number sequence (potential account ID)."
    echo "Please double-check staged changes for private account IDs before pushing to public repos."
fi

echo "✅ Pre-commit security check passed."
exit 0
EOF

chmod +x "$PRE_COMMIT_HOOK"
echo "✅ Git pre-commit security hook successfully installed to $PRE_COMMIT_HOOK!"
