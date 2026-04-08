#!/usr/bin/env bash
set -euo pipefail

# AI Burst Cloud — Repo Audit Script
# Checks consistency across code, docs, packaging, and skills.
#
# Usage:
#   ./scripts/audit.sh           # run all checks
#   ./scripts/audit.sh --fix     # show suggestions for fixes

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
WARN=0

pass() { ((PASS++)); printf "  \033[32m✓\033[0m %s\n" "$1"; }
fail() { ((FAIL++)); printf "  \033[31m✗\033[0m %s\n" "$1"; }
warn() { ((WARN++)); printf "  \033[33m!\033[0m %s\n" "$1"; }
section() { printf "\n\033[1m%s\033[0m\n" "$1"; }

# ─── Version Consistency ──────────────────────────────────────────

section "Version consistency"

VERSION_PYPROJECT=$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
VERSION_INIT=$(grep '__version__' app/__init__.py | sed 's/.*"\(.*\)".*/\1/')
VERSION_SKILL=$(grep '^version:' skills/aiburstcloud/SKILL.md 2>/dev/null | sed 's/version: //')

if [ "$VERSION_PYPROJECT" = "$VERSION_INIT" ]; then
    pass "pyproject.toml ($VERSION_PYPROJECT) matches app/__init__.py ($VERSION_INIT)"
else
    fail "pyproject.toml ($VERSION_PYPROJECT) != app/__init__.py ($VERSION_INIT)"
fi

if [ -n "$VERSION_SKILL" ]; then
    if [ "$VERSION_PYPROJECT" = "$VERSION_SKILL" ]; then
        pass "pyproject.toml ($VERSION_PYPROJECT) matches SKILL.md ($VERSION_SKILL)"
    else
        fail "pyproject.toml ($VERSION_PYPROJECT) != SKILL.md ($VERSION_SKILL)"
    fi
else
    warn "No version found in SKILL.md"
fi

# ─── Required Files ───────────────────────────────────────────────

section "Required files"

for f in pyproject.toml README.md LICENSE Dockerfile docker-compose.yml \
         .env.example .gitignore install.sh \
         app/__init__.py app/router.py app/cli.py app/__main__.py \
         skills/aiburstcloud/SKILL.md skills/aiburstcloud/nemoclaw/network-policy.yaml; do
    if [ -f "$f" ]; then
        pass "$f exists"
    else
        fail "$f missing"
    fi
done

# ─── Environment Variables ────────────────────────────────────────

section "Environment variable documentation"

# Extract env vars used in router.py (os.getenv / os.environ patterns)
ROUTER_VARS=$(grep -oE 'os\.(getenv|environ\.get|environ\[)\("?[A-Z0-9_]+' app/router.py | \
    grep -oE '[A-Z][A-Z0-9_]+' | sort -u)

# Check each is documented in README
for var in $ROUTER_VARS; do
    if grep -q "$var" README.md; then
        pass "$var documented in README"
    else
        fail "$var used in router.py but missing from README"
    fi
done

# Check each is in .env.example (at least the key ones)
for var in BURST_MODE LOCAL_URL LOCAL_MODEL CLOUD_URL CLOUD_MODEL CLOUD_API_KEY DAILY_CLOUD_BUDGET_USD; do
    if grep -q "^$var" .env.example; then
        pass "$var in .env.example"
    else
        fail "$var missing from .env.example"
    fi
done

# ─── Dependencies ─────────────────────────────────────────────────

section "Dependency consistency"

# Check pyproject.toml deps match requirements.txt
PYPROJECT_DEPS=$(grep -E '^\s+"[a-z]' pyproject.toml | sed 's/.*"\([a-z][a-z0-9_-]*\).*/\1/' | sort)
if [ -f requirements.txt ]; then
    REQ_DEPS=$(sed 's/[>=<\[].*//' requirements.txt | tr '[:upper:]' '[:lower:]' | sort)
    MISSING_FROM_REQ=$(comm -23 <(echo "$PYPROJECT_DEPS") <(echo "$REQ_DEPS"))
    MISSING_FROM_PYPROJECT=$(comm -13 <(echo "$PYPROJECT_DEPS") <(echo "$REQ_DEPS"))

    if [ -z "$MISSING_FROM_REQ" ] && [ -z "$MISSING_FROM_PYPROJECT" ]; then
        pass "pyproject.toml and requirements.txt dependencies match"
    else
        [ -n "$MISSING_FROM_REQ" ] && fail "In pyproject.toml but not requirements.txt: $MISSING_FROM_REQ"
        [ -n "$MISSING_FROM_PYPROJECT" ] && fail "In requirements.txt but not pyproject.toml: $MISSING_FROM_PYPROJECT"
    fi
else
    warn "requirements.txt not found (optional if using pyproject.toml only)"
fi

# ─── README Install Methods ──────────────────────────────────────

section "README install methods"

for method in "pip install" "docker compose" "install.sh" "openclaw skills install"; do
    if grep -q "$method" README.md; then
        pass "README documents: $method"
    else
        fail "README missing install method: $method"
    fi
done

# ─── Dockerfile ───────────────────────────────────────────────────

section "Dockerfile"

if grep -q "pip install" Dockerfile; then
    pass "Dockerfile uses pip install"
else
    warn "Dockerfile may not use pip-based install"
fi

if grep -q "EXPOSE" Dockerfile; then
    DOCKER_PORT=$(grep "EXPOSE" Dockerfile | awk '{print $2}')
    pass "Dockerfile exposes port $DOCKER_PORT"
else
    fail "Dockerfile missing EXPOSE directive"
fi

# ─── Skill Validation ────────────────────────────────────────────

section "OpenClaw skill"

SKILL_FILE="skills/aiburstcloud/SKILL.md"
if [ -f "$SKILL_FILE" ]; then
    # Check required frontmatter fields
    for field in "name:" "description:" "when:"; do
        if grep -q "^$field" "$SKILL_FILE"; then
            pass "SKILL.md has $field"
        else
            fail "SKILL.md missing $field"
        fi
    done

    # Check skill name matches package name
    SKILL_NAME=$(grep '^name:' "$SKILL_FILE" | sed 's/name: //')
    PACKAGE_NAME=$(grep '^name' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
    if [ "$SKILL_NAME" = "$PACKAGE_NAME" ]; then
        pass "Skill name ($SKILL_NAME) matches package name ($PACKAGE_NAME)"
    else
        warn "Skill name ($SKILL_NAME) differs from package name ($PACKAGE_NAME)"
    fi
fi

# ─── NemoClaw Policy ─────────────────────────────────────────────

section "NemoClaw network policy"

POLICY_FILE="skills/aiburstcloud/nemoclaw/network-policy.yaml"
if [ -f "$POLICY_FILE" ]; then
    for endpoint in "local_inference" "cloud_inference" "github"; do
        if grep -q "$endpoint" "$POLICY_FILE"; then
            pass "Policy defines $endpoint endpoint group"
        else
            fail "Policy missing $endpoint endpoint group"
        fi
    done
else
    fail "NemoClaw network policy not found"
fi

# ─── Links ────────────────────────────────────────────────────────

section "Repository links"

EXPECTED_ORG="aiburstcloud/aiburstcloud"
for file in README.md skills/aiburstcloud/SKILL.md; do
    if [ -f "$file" ]; then
        if grep -q "github.com/$EXPECTED_ORG" "$file"; then
            pass "$file points to $EXPECTED_ORG"
        else
            OLD_REFS=$(grep -o 'github.com/[a-zA-Z0-9_-]*/aiburstcloud' "$file" | grep -v "$EXPECTED_ORG" | head -3)
            if [ -n "$OLD_REFS" ]; then
                fail "$file has stale repo links: $OLD_REFS"
            else
                warn "$file may not reference GitHub repo"
            fi
        fi
    fi
done

# ─── Git Status ───────────────────────────────────────────────────

section "Git status"

UNCOMMITTED=$(git status --porcelain 2>/dev/null | { grep -v '^\?\?' || true; } | wc -l | tr -d '[:space:]')
UNTRACKED=$(git status --porcelain 2>/dev/null | { grep '^\?\?' || true; } | wc -l | tr -d '[:space:]')

if [ "$UNCOMMITTED" -eq 0 ]; then
    pass "No uncommitted changes"
else
    warn "$UNCOMMITTED uncommitted change(s)"
fi

if [ "$UNTRACKED" -gt 0 ]; then
    warn "$UNTRACKED untracked file(s)"
fi

# Check remote is set to org
REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "none")
if echo "$REMOTE_URL" | grep -q "aiburstcloud/aiburstcloud"; then
    pass "Remote origin points to aiburstcloud org"
else
    fail "Remote origin ($REMOTE_URL) not pointing to aiburstcloud org"
fi

# ─── Summary ──────────────────────────────────────────────────────

printf "\n\033[1m━━━ Audit Summary ━━━\033[0m\n"
printf "  \033[32m%d passed\033[0m  " "$PASS"
printf "\033[31m%d failed\033[0m  " "$FAIL"
printf "\033[33m%d warnings\033[0m\n\n" "$WARN"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
