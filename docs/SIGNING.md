# EDLD Release Signing

All EDLD commits, tags, and release artifacts are signed with an SSH key.

---

## Verifying a release artifact

A release on the [releases page](https://github.com/drworman/EDLD/releases)
carries five files: three artefacts, a checksum manifest listing all three, and
one detached signature over that manifest.

| File | Contents |
|------|----------|
| `EDLD-<version>-linux-x86_64.tar.gz` | Linux binary |
| `EDLD-<version>-windows-x86_64.zip` | Windows binary |
| `EDLD-<version>-macos-arm64.zip` | macOS binary |
| `EDLD-<version>.sha256` | SHA-256 of all three, one per line |
| `EDLD-<version>.sha256.sig` | SSH signature over that manifest |

GitHub also attaches its own *Source code (zip)* and *Source code (tar.gz)* to
every release, generated from the tag. Those are the source download. They are
produced by GitHub rather than by the release workflow, so they are not part of
the manifest and carry no signature of ours.

To obtain source you can verify, clone the repository and check out the signed
tag — every EDLD tag is signed with the same key:

```
git clone https://github.com/drworman/EDLD.git
cd EDLD
git verify-tag <version>
```

That authenticates the source through git's own object hashing, which is a
stronger guarantee than a digest in a manifest: it covers the full history, not
one snapshot.

The artefacts are not signed individually. The manifest names each one by
digest and the manifest itself is signed, so a valid signature plus a matching
digest gives the same guarantee for any file, and one signature check covers
the whole release. Verification is therefore two steps:

1. The signature on `EDLD-<version>.sha256` is valid for `signing_key.pub`.
2. Your file's SHA-256 matches its line in that manifest.

**Step 2 is worthless without step 1.** Anyone who alters an artefact can
recompute its checksum and rewrite the manifest; what they cannot do is
re-sign it. Never check a digest against a manifest whose signature you have
not verified.

The Windows and macOS binaries may also carry a platform code signature
(Authenticode, and Apple notarisation), which your operating system checks by
itself. The signature here is independent of that and can be verified on any
platform.

**Quick verify:**

```bash
# One artifact
bash scripts/verify_release.sh EDLD-20260830-linux-x86_64.tar.gz

# Or every artifact you downloaded, from the download directory
bash scripts/verify_release.sh
```

**Manual verify:**

```bash
# Build an allowed_signers file from the repo public key
echo "drworman namespaces=\"edld.release\" $(cat signing_key.pub)" > allowed_signers

# 1. Authenticate the manifest — this must pass before the checksums mean
#    anything at all
ssh-keygen -Y verify \
    -f allowed_signers \
    -I drworman \
    -n edld.release \
    -s EDLD-20260830.sha256.sig \
    < EDLD-20260830.sha256

# 2. Check your download against the now-trusted manifest.
#    --ignore-missing checks only the files you actually downloaded.
sha256sum -c --ignore-missing EDLD-20260830.sha256

rm allowed_signers
```

---

## Signing key

The release signing public key is committed to the repo at `signing_key.pub`.
It is registered on GitHub as a signing key, causing all commits and tags
mirrored from the primary server to display a **Verified** badge.

---

## Signed commits and tags

All commits on `main` and `dev` are SSH-signed. To verify a commit locally:

```bash
# One-time setup — add the key to your allowed_signers file
echo "drworman namespaces=\"git\" $(cat signing_key.pub)" >> ~/.ssh/allowed_signers
git config --global gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers

# Verify any commit
git log --show-signature -1

# Verify a specific tag
git tag -v 20260409
```

---

## Release flow

EDLD uses `git.indevlin.com` (`idev`) as the authoritative source and GitHub
(`ghub`) as a passive mirror. The release process follows this order:

```
1. Finish work on dev, merge to main
2. git checkout main
3. git tag -s 20260409 -m 'Release 20260409'   # signed tag
4. gpublish                                     # push to idev, mirror to ghub
5. GitHub -> Releases -> Draft a new release
   Select the tag -> write notes -> Publish
   (the release workflow fires automatically)
```

The GitHub Actions release workflow runs only when you manually publish a
release on GitHub. It builds the three binaries, generates the checksum
manifest, signs that manifest with the stored `SIGNING_KEY` secret, then
verifies in-CI exactly what a user verifies — the signature on the manifest,
followed by every digest in it — before uploading the five files to the
release. It also asserts the manifest covers three artefacts, so a glob that
quietly matched fewer would fail the build rather than ship a release that
verifies cleanly while missing a platform.

---

## Developer setup (maintainer only)

Run the setup script once from the repo root:

```bash
bash scripts/setup_signing.sh
```

Two GitHub Actions secrets are required (Settings → Secrets → Actions):

| Secret             | Content                                                                             |
| ------------------ | ----------------------------------------------------------------------------------- |
| `SIGNING_KEY`      | Private SSH key (ed25519, no passphrase)                                            |
| `SIGNING_IDENTITY` | Identifier used when signing — must match `SIGNING_IDENTITY` in `verify_release.sh` |
