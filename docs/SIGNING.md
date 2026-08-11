# EDLD Release Signing

All EDLD commits, tags, and release artifacts are signed with an SSH key.

---

## Verifying a release artifact

Every file on the [releases page](https://github.com/drworman/EDLD/releases) is
accompanied by a detached signature (`.sig`), and a single `.sha256` file covers
the whole release.

A release carries four artefacts plus their signatures:

| File | Contents |
|------|----------|
| `EDLD-<version>.tar.gz` | Source |
| `EDLD-<version>-linux-x86_64.tar.gz` | Linux binary |
| `EDLD-<version>-windows-x86_64.zip` | Windows binary |
| `EDLD-<version>-macos-arm64.zip` | macOS binary |
| `EDLD-<version>.sha256` | Checksums for all of the above |

The commands below use the source tarball; they work the same for any of them —
substitute the filename.

The Windows and macOS binaries may also carry a platform code signature
(Authenticode, and Apple notarisation), which your operating system checks by
itself. The SSH signatures here are independent of that and can be verified on
any platform.

**Quick verify:**

```bash
bash scripts/verify_release.sh EDLD-20260811.tar.gz
```

**Manual verify:**

```bash
# Build an allowed_signers file from the repo public key
echo "drworman namespaces=\"edld.release\" $(cat signing_key.pub)" > allowed_signers

# Verify the signature
ssh-keygen -Y verify \
    -f allowed_signers \
    -I drworman \
    -n edld.release \
    -s EDLD-20260811.tar.gz.sig \
    < EDLD-20260811.tar.gz

# Verify the checksum
sha256sum -c EDLD-20260811.sha256

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
release on GitHub. It builds the source tarball, generates checksums, signs
everything with the stored `SIGNING_KEY` secret, verifies all signatures
in-CI, then uploads the artifacts to the release.

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
