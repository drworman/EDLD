# EDLD Release Signing

All EDLD commits, tags, and release artifacts are signed with an SSH key.

---

## Verifying a release artifact

Every file on the [releases page](https://github.com/drworman/EDLD/releases) is
accompanied by a detached signature (`.sig`) and a SHA-256 checksum (`.sha256`).

**Quick verify:**

```bash
bash scripts/verify_release.sh EDLD-20260409.tar.gz
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
    -s EDLD-20260409.tar.gz.sig \
    < EDLD-20260409.tar.gz

# Verify the checksum
sha256sum -c EDLD-20260409.sha256

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
