# Drafter check

The drafter turns a guide's written directions into instructions with fixed
patterns. Guides are written for people, so it will always misread some mods
(see [What drafts get wrong](../site/instruction-files.html#draft-mistakes)).
Every draft therefore needs a human review after it is made, and nothing
drafted installs until it has one.

CI follows the same rule. It should install from a **reviewed instruction
set**: the guide's instructions, drafted once, checked and fixed by a person,
marked reviewed, and pinned to one version of the guide. The drafter check is
an optional gate on top of that. It drafts the same guide version again and
lists every component where the fresh draft differs from the reviewed set, so
drafter changes can be judged against real, reviewed data.

A difference is not a failure on its own. It shows where the drafter would have
needed a human.

## Making a reviewed set

Use one exact `kolto-labs/mod-builds` version, for example tag `v12.3.15`.

```sh
git -C mod-builds checkout v12.3.15
modsync convert mod-builds/content/k1/full.md k1-full.draft.json --parse-directions
```

Review every drafted component against its archive, the guide and the mod's
readme, as described in
[How to review a draft](../site/instruction-files.html#draft-review). Fix
wrong steps in the file or the desktop editor, write steps by hand where the
drafter gave none, then mark each component reviewed:

```sh
modsync convert k1-full.draft.json k1-full.reviewed.json --review-draft <guid> --review-draft <guid> ...
modsync validate --input k1-full.reviewed.json --game-dir <test copy> --source-dir <mods>
```

Keep the component GUIDs the converter gave: the check matches components by
GUID, then by name. JSON keeps every review receipt; TOML cannot encode some
of them (see `COMPATIBILITY.md`).

## Pinning it

Attach the reviewed file to the matching `kolto-labs/mod-builds` version, as a
release asset or as a file committed at that tag, so the guide and its
reviewed instructions always travel together. Then add it to
[`.github/reviewed-instructions.json`](../.github/reviewed-instructions.json):

```json
{
  "sets": [
    {
      "name": "k1-full",
      "guide_ref": "v12.3.15",
      "guide_path": "content/k1/full.md",
      "guide_sha256": "<sha256 of full.md at that tag>",
      "reviewed_url": "https://github.com/kolto-labs/mod-builds/releases/download/v12.3.15/k1-full.reviewed.json",
      "reviewed_sha256": "<sha256 of the reviewed file>"
    }
  ]
}
```

`reviewed_sha256` is required. A download whose hash does not match stops the
check.

## Running it

The workflow is `.github/workflows/drafter-check.yml`. Repository variables
control it:

| Variable | Effect |
|---|---|
| `RUN_DRAFTER_CHECK` | `true` runs it on pull requests that touch the drafter, the Markdown reader, the manifest or the tool. It can always be started by hand. |
| `DRAFTER_CHECK_STRICT` | `true` fails the job when a draft differs from the reviewed set. Off, differences are only reported. |
| `DRAFTER_CHECK_REQUIRED` | `true` lets a failed job block the run. Off, the job may fail without failing the workflow. |

The job always fails, whatever `DRAFTER_CHECK_STRICT` says, when the reviewed
set is not clean: a component in it still needs review, or a component is only
in the guide or only in the reviewed set.

Locally:

```sh
python3 tools/compare_drafts.py --binary target/debug/modsync \
  --guide full.md --reviewed k1-full.reviewed.json --output drafter-check
python3 tools/compare_drafts.py --binary target/debug/modsync \
  --manifest .github/reviewed-instructions.json --output drafter-check
```

Each comparison writes `report.json` (every component, and for each difference
the drafted and reviewed steps side by side) and `summary.md`, which also goes
to the GitHub job summary. Steps are compared on their action, sources,
destination, arguments and overwrite flag, and options on their name,
selection and steps.

## Using reviewed sets in the other CI jobs

The synthetic full-build proofs still draft `full.md` on every run and prove
that the unreviewed drafts are refused. Once a reviewed set is pinned for a
guide version, those jobs can take it as their instruction file instead, so
everything after drafting runs on reviewed data. That change is left for when
the first reviewed set exists.
