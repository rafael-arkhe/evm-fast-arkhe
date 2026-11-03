# evm.fast (Yukon `lean` track) with ARKHE checks

Tooling to work on `eigenlabs/evm-fast/lean` with a fail-closed setup and a checker
that is independent of the solver. It never replaces the official verifier
(`scripts/run.py`, comparator mode); it runs before `yukon submit`.

| File | Role |
|---|---|
| `vm-bootstrap.sh` | Checks the VM (Linux, systemd 257+, Landlock, case-sensitive disk, space), installs the Yukon CLI only from the audited `install.sh` hash, turns traces and telemetry off before any other `yukon` command, clones and starts `yukon setup --track lean` in tmux. |
| `arkhe_precheck.py` | Scope against `editablePaths`, banned Lean constructs (`sorry`, `native_decide`, `axiom`, `implemented_by`, `@[extern]`, build-time code), `claim.json` vs `claimedScore`, and optionally the `#print axioms` line of a build log. Writes a JSON receipt with the base commit and file hashes. |

## VM

Ubuntu 25.04+ or Fedora 42+ (systemd 257+), about 128 GB RAM, 32 vCPUs, 300 GB disk.

```bash
read -rs YUKON_API_TOKEN && export YUKON_API_TOKEN
bash vm-bootstrap.sh ~/evm-fast
```

## Before submitting

```bash
python3 -I arkhe_precheck.py ~/evm-fast --base "$(cat ~/evm-fast.base-commit)" \
  --axioms-log build.log --receipt receipt.json
```

`PASS` needs the build log; without it the verdict is `PARTIAL` (static evidence only).
Submission still requires the official `verified` result.

## License

Apache License 2.0. See [LICENSE](LICENSE).
