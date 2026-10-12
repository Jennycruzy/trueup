# Owner actions

Nothing below has been posted or enabled by Trueup. Review each draft and patch before running these commands.

## 1. Post the two prepared Neatlogs fixes

Refusal output:

```sh
gh issue create --repo neatlogs/neatlogs --title "OpenAI Chat Completions: refusal text is missing from the output span" --body-file upstream/neatlogs-output-openai-chat-create-output-text-missing/issue.md
git -C .trueup/clones/neatlogs switch -c fix/openai-chat-refusal-output
git -C .trueup/clones/neatlogs apply ../../../fixes/neatlogs-output-openai-chat-create-output-text-missing/patch.diff
git -C .trueup/clones/neatlogs push Jennycruzy HEAD
gh pr create --repo neatlogs/neatlogs --base main --head Jennycruzy:fix/openai-chat-refusal-output --title "fix(openai): record refusal text as chat output" --body-file upstream/neatlogs-output-openai-chat-create-output-text-missing/pr.md
```

Responses stream error events:

```sh
git -C .trueup/clones/neatlogs switch main
gh issue create --repo neatlogs/neatlogs --title "OpenAI Responses: a stream error event leaves the span status unset" --body-file upstream/neatlogs-run_status-openai-responses-stream-top-level-span-status-unset/issue.md
git -C .trueup/clones/neatlogs switch -c fix/openai-responses-stream-errors
git -C .trueup/clones/neatlogs apply ../../../fixes/neatlogs-run_status-openai-responses-stream-top-level-span-status-unset/patch.diff
git -C .trueup/clones/neatlogs push Jennycruzy HEAD
gh pr create --repo neatlogs/neatlogs --base main --head Jennycruzy:fix/openai-responses-stream-errors --title "fix(openai): record Responses stream error events" --body-file upstream/neatlogs-run_status-openai-responses-stream-top-level-span-status-unset/pr.md
```

The commands assume the clone has a `Jennycruzy` remote pointing to the owner's Neatlogs fork. Add that remote first if it is absent. Do not post the OpenAI Agents candidate: all three drafts failed the real scenarios.

## 2. Existing presentation and account actions

- Capture the Neatlogs dashboard views listed in `docs/neatlogs.md`.
- Review and publish the video; `docs/video-script.md` remains local and excluded from git.
- Enable GitHub Pages for `docs/` if the public evidence page is wanted.
- Add `NEATLOGS_API_KEY` to repository Actions only if nightly trace export is approved.
- Review the prepared X posts in `docs/posts.md`; Trueup does not post them.
