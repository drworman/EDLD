#!/usr/bin/env bash
# scripts/sync_wiki.sh
#
# Copies EDLD docs from the main repo into the wiki repo.
# Fully auto-discovers all docs and guides — no changes needed when new
# files are added to docs/ or docs/guides/.
#
# Naming convention (applied automatically):
#   README.md                       → Home.md           (special case)
#   INSTALL.md                      → Installation.md   (special case)
#   docs/SOME_DOC.md                → Some-Doc.md       (auto)
#   docs/guides/SOME_GUIDE.md       → Some-Guide.md     (auto)
#   docs/releases/RELEASE_NOTES_*   → combined into Release-Notes.md (auto)
#
# Adding a new guide or doc: just create the file. Nothing else needed.
# Adding a new abbreviation that needs special casing: add a line to the
# case block in to_wiki_name() below.
#
# Usage (local):
#   WIKI_DIR=/path/to/EDLD.wiki bash scripts/sync_wiki.sh
#
# Usage (CI — called by .github/workflows/sync-wiki.yml):
#   Env vars WIKI_DIR and REPO_DIR are set by the workflow.
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)}"
WIKI_DIR="${WIKI_DIR:-}"

if [[ -z "$WIKI_DIR" ]]; then
    echo "ERROR: WIKI_DIR is not set." >&2
    exit 1
fi

echo "Syncing docs to wiki at: $WIKI_DIR"

# ── Filename → wiki page name ─────────────────────────────────────────────────
# Strips path and .md extension, lowercases each word, title-cases, joins with
# hyphens.  Special cases handle branding and the two fixed root files.
#
# To add a new special case (e.g. a guide whose name needs non-standard casing):
#   add a line:  SOME_FILENAME) echo "Desired-Name"; return ;;
#
to_wiki_name() {
    local _src="$1"
    local _base
    _base="$(basename "$_src" .md)"

    case "$_base" in
        README)        echo "Home";         return ;;
        INSTALL)       echo "Installation"; return ;;
    esac

    # General rule: split on underscores/hyphens, lowercase each word,
    # capitalise first letter, rejoin with hyphens.
    echo "$_base" \
        | tr '_' '-' \
        | sed -E 's/-+/-/g' \
        | awk -F'-' '{
            for(i=1;i<=NF;i++){
                w=tolower($i)
                printf "%s%s", toupper(substr(w,1,1)) substr(w,2), (i<NF ? "-" : "")
            }
          }'
}

# ── Discover all source files and build name registry ─────────────────────────
declare -A WIKI_NAMES   # src_rel → wiki page name (no .md)

register() {
    local _src_rel="$1"
    local _wiki_name
    _wiki_name="$(to_wiki_name "$_src_rel")"
    WIKI_NAMES["$_src_rel"]="$_wiki_name"
}

register "README.md"
register "INSTALL.md"

for _f in "$REPO_DIR"/docs/*.md; do
    [[ -f "$_f" ]] || continue
    register "docs/$(basename "$_f")"
done

for _f in "$REPO_DIR"/docs/guides/*.md; do
    [[ -f "$_f" ]] || continue
    register "docs/guides/$(basename "$_f")"
done

# ── Link rewriter ─────────────────────────────────────────────────────────────
# Rewrites every internal markdown link to its wiki equivalent.
# Uses private variable names (_rw_*) to avoid clobbering outer loop variables.
rewrite_links() {
    local _file="$1"
    local _rw_rel _rw_name
    for _rw_rel in "${!WIKI_NAMES[@]}"; do
        _rw_name="${WIKI_NAMES[$_rw_rel]}"
        sed -i -E "s|\]\(${_rw_rel}(#[^)]*)?\)|\](${_rw_name}\1)|g" "$_file"
    done
}

# ── Image path rewriter ───────────────────────────────────────────────────────
# The wiki is a separate git repo and has no access to the main repo's images/
# directory.  Rewrite all relative image paths to absolute raw.githubusercontent
# URLs so images render correctly on every wiki page.
#
# Handles:
#   src="images/foo.png"      (README — same-level path)
#   src="../images/foo.png"   (docs/* — one level up)
#   ![alt](images/foo.png)    (markdown style, same-level)
#   ![alt](../images/foo.png) (markdown style, one level up)
#
GITHUB_RAW="https://raw.githubusercontent.com/${GITHUB_REPOSITORY:-drworman/EDLD}/main"

rewrite_images() {
    local _file="$1"
    # HTML src attributes — both ../images/ and images/
    sed -i -E \
        's|src="(\.\./)?images/([^"]+)"|src="'"$GITHUB_RAW"'/images/\2"|g' \
        "$_file"
    # Markdown image syntax — both ../images/ and images/
    sed -i -E \
        's|!\[([^]]*)\]\((\.\./)?images/([^)]+)\)|![\1]('"$GITHUB_RAW"'/images/\3)|g' \
        "$_file"
}

# ── Copy individual docs ──────────────────────────────────────────────────────
for src_rel in "${!WIKI_NAMES[@]}"; do
    src="$REPO_DIR/$src_rel"
    wiki_name="${WIKI_NAMES[$src_rel]}"
    dst="$WIKI_DIR/${wiki_name}.md"
    if [[ -f "$src" ]]; then
        cp "$src" "$dst"
        rewrite_links "$dst"
        rewrite_images "$dst"
        echo "  copied: $src_rel → ${wiki_name}.md"
    else
        echo "  WARNING: source not found — $src_rel" >&2
    fi
done

# ── Combine release notes → Release-Notes.md (newest first) ──────────────────
RELEASES_DIR="$REPO_DIR/docs/releases"
RELEASE_OUT="$WIKI_DIR/Release-Notes.md"

echo "# Release Notes" > "$RELEASE_OUT"
echo "" >> "$RELEASE_OUT"

while IFS= read -r _rn_file; do
    echo "---" >> "$RELEASE_OUT"
    echo "" >> "$RELEASE_OUT"
    cat "$_rn_file" >> "$RELEASE_OUT"
    echo "" >> "$RELEASE_OUT"
done < <(ls "$RELEASES_DIR"/RELEASE_NOTES_*.md 2>/dev/null | sort -r)

echo "  combined: docs/releases/ → Release-Notes.md"

# ── Auto-generate _Sidebar.md ─────────────────────────────────────────────────
# Sections are fixed (Getting Started / Guides / Reference / Releases).
# Pages within Guides and Reference are discovered from what was copied,
# sorted alphabetically.  New docs appear in the sidebar automatically.
SIDEBAR="$WIKI_DIR/_Sidebar.md"

{
    echo "## EDLD Wiki"
    echo ""
    echo "**Getting Started**"
    echo "- [[Home]]"
    echo "- [[Installation]]"
    echo ""
    echo "**Guides**"
    while IFS= read -r _sb_f; do
        _sb_rel="docs/guides/$(basename "$_sb_f")"
        _sb_name="${WIKI_NAMES[$_sb_rel]:-}"
        [[ -z "$_sb_name" ]] && continue
        _sb_label="${_sb_name//-/ }"
        echo "- [[$_sb_name|$_sb_label]]"
    done < <(ls "$REPO_DIR"/docs/guides/*.md 2>/dev/null | sort)
    echo ""
    echo "**Reference**"
    while IFS= read -r _sb_f; do
        _sb_rel="docs/$(basename "$_sb_f")"
        _sb_name="${WIKI_NAMES[$_sb_rel]:-}"
        [[ -z "$_sb_name" ]] && continue
        _sb_label="${_sb_name//-/ }"
        echo "- [[$_sb_name|$_sb_label]]"
    done < <(ls "$REPO_DIR"/docs/*.md 2>/dev/null | sort)
    echo ""
    echo "**Releases**"
    echo "- [[Release-Notes|Release Notes]]"
} > "$SIDEBAR"

echo "  wrote: _Sidebar.md"
echo ""
echo "Sync complete."
