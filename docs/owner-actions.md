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

Before the presentation, add the two trace-level code detections in Neatlogs. In **Detections → New detection →
Code**, name the first `Trueup: crashed run shown as OK`, paste the complete contents of
`detections/crashed_run_ok.py`, preview it, save only if the preview matches a known demo trace, and place it in
`Trace truth (by Trueup)`. Repeat with name `Trueup: duplicate LLM call`, file
`detections/duplicate_llm_calls.py`, and the same group. The available MCP write surface cannot create code-engine
detections, so these are deliberately owner actions.

Then run the exact screenshot checks in `docs/neatlogs.md`; capture the detection list and the hit on trace
`6041090c2877aa7d78861796ee052fcb`.

- Capture the Neatlogs dashboard views listed in `docs/neatlogs.md`.
- Review and publish the video; `docs/video-script.md` remains local and excluded from git.
- Enable GitHub Pages for `docs/` if the public evidence page is wanted.
- Add `NEATLOGS_API_KEY` to repository Actions only if nightly trace export is approved.
- Review the prepared X posts in `docs/posts.md`; Trueup does not post them.
# Witness owner actions

1. In neatlogs, open Alerts and create a rule for detection `TRACE DISAGREE light`, threshold at least one occurrence. Choose a notification destination and enable the rule.
2. Record the 2:30 script in `docs/video-script.md`. Use a drawn cockpit panel, no crash footage, and show the 2 → 0 result with the before and after traces. Say once that our first try stayed 2 → 2.
3. Replace `[VIDEO_URL]` only after uploading the final video.
4. Post the drafts in `docs/posts.md` yourself. Trueup has not posted them.
