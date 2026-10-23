# Output contract

Read this reference before processing or delivering files.

## Character workspace

All generated artifacts for one character live under `works/<character-slug>/` in the skill directory. Resolve it with `scripts/character_workspace.py --name <角色名>`. Do not add new job files to a shared `work/` folder or the skill root.

```text
works/<character-slug>/
├── character.json
├── static-sheet-source.png
├── static-sheet.png
├── static-prompt.json
├── static-generation.json
├── static-generation-attempts.json
├── static-alpha.json
├── layout.json
├── job-state.json
├── tile-plan.json
├── keypose-plan/             # keypose-local only
│   └── keypose-plan.json
├── keypose-sheets/           # externally generated 2×2 sheets
├── keyposes/                 # validated four-pose frames
│   └── keypose-preparation.json
├── prompts.json
├── video-task.json
├── route.json
├── attempt-ledger.json
├── artifact-manifest.json
├── raw-video/
│   └── <provider>.mp4           # one accepted canonical source video
└── delivered/                   # numbered stickers + reports + one ZIP
```

Public Gallery cases additionally carry `provenance.json`. It is a compact,
machine-checkable summary of input type, route/model, native frame evidence,
successful/withheld cells, output hashes and sizes. A legacy record must list
missing approval or manifest history explicitly; it may not infer user approval
from a route or task hash.

## Required generic package

```text
works/<character-slug>/delivered/
├── 01.webp ... NN.webp
├── 01.gif  ... NN.gif
├── 01.png  ... NN.png
├── preview.png                  light checkerboard review composite
├── layout.json
├── job-state.json               when static approval was required
├── prompts.json                 when generation occurred
├── route.json                   when routing occurred
├── attempt-ledger.json          paid-attempt status and transition history
├── video-retry-approval.json    only when a user-approved retry occurred
├── artifact-manifest.json       SHA-256 artifact lineage snapshot
├── processing.json
├── 3s/                          Grok only: 24-frame derivative + reports
└── sticker-pack.zip
```

Number files in row-major order with at least two digits. `NN` must equal `detected_layout.count`, not a count copied from the initial prompt.
For independent static stickers, `layout.json` may declare a synthetic single-row numbering layout and must also record `source_type: separate-static-stickers`.

## Processing rules

- The default profiles are 3 seconds → 240×240 at 8 fps (24 frames) and 6 seconds → 240×240 at 8 fps (48 frames), both with a 192-color GIF palette ceiling.
- For a direct API provider that supports 3 seconds, request 3 seconds and preserve the matching returned duration as the only version. Do not retime it; an unexpected duration must stop and report.
- For Grok-generated grid videos, retain the complete returned 6-second duration in the root output. Also create `3s/` from the initial 24 sampled frames. Record the first/last endpoint difference for audit, but do not reject or retime the 3-second derivative when the poses differ.
- Keep one accepted provider video under `raw-video/`. An accepted attempt is promoted to the canonical provider filename instead of copied, while a rejected attempt may remain for diagnosis.
- Whole-grid registration is off by default. Enable it only for verified camera drift; frame-by-frame integer translation can create visible micro-jitter in an otherwise fixed-camera source.
- Preserve aspect ratio inside each detected cell. Do not stretch a crop to square unless a target platform profile explicitly requires a square canvas with padding.
- Prefer a real source alpha channel. Otherwise estimate the uniform background from corners and borders, then remove only background-like regions connected to the crop edge.
- A video declared as chroma-screen must pass strict QC before matting: every native frame's corners and border must match the task's declared key color, whether green, magenta, or another validated high-contrast color. A gray/white checkerboard is not transparency and must be rejected, not color-inferred or globally deleted. Opaque-scene video bypasses this QC and keeps its background.
- For grid videos, repack each cell from its actual Alpha bounding box, targeting roughly 70%–75% foreground-bbox occupancy and never exceeding 75%, so every side has at least a 10% green safety corridor. Decode and inspect every native frame. Internal-seam crossings are evidence for instance assignment and safe-window selection, not automatic whole-video failure; small accents do not count as independent subjects when a full-size component is fused across a seam. A short balanced merge run (up to 0.2 seconds) may be repaired from temporally adjacent safe frames and must be recorded; longer or identity-ambiguous merges remain bad frames.
- Avoid global color deletion: a face, garment, or prop similar to the key color must remain opaque when not connected to the outer background.
- Near-black and near-white plates use a tight key automatically. Default chroma radii eat dark fur or light clothing, and GIF binary transparency turns those pixels into holes on a light chat or README background.
- Retain a clean first-frame transparent PNG for each animation.
- Also export a looping GIF per cell for platforms that do not accept Animated WebP. GIF transparency is binary (palette), not a full alpha channel; choose from bounded alpha-threshold candidates using fringe retention, edge erosion, and temporal coverage. Do not score visible green as spill without key-region evidence: it may be the subject's own color. Treat Animated WebP as the quality-preferred format.
- For `keypose-local`, require the approved image/layout/state on plan compilation and preparation, require exactly `01-start.png`, `02-anticipation.png`, `03-peak.png`, and `04-recovery.png` per sticker, and decode both final formats for encoded-output QC before packaging.
- Package only delivery artifacts and reports; omit temporary raw-frame directories. When this Skill generated the static sheet, include `static-prompt.json`, `static-generation.json`, and `static-alpha.json` so parameter fallback and alpha repair remain auditable.
- For transparent-grid static generation, `static-generation.json` must preserve the input mode, resolved background policy, bounded opaque retry, omitted schema fields, single-call execution protocol, and selected attempt. `static-generation-attempts.json` must record every claimed/invoked/accepted/rejected attempt. Reference-image generation uses a uniform plate if native Alpha is unreliable: green is only the default, and a subject containing green needs a contrasting key. Text-defined generation is transparent-first when supported but still requires pixel validation. A checkerboard/two-tone result is a failed attempt and must never be recorded as an accepted normalized source. A missing `content` array is not enough to start another attempt when a top-level `image_url`, `output_hint`, data URL, bytes, or saved artifact exists. An opaque-scene first frame retains its complete background and follows the separate album route.
- Use `scripts/assemble_delivery.py --cleanup-media-dir` to collect media and audit artifacts into the canonical `delivered/` directory and remove the intermediate media directory after the ZIP succeeds. The ZIP must include `job-state.json`, `prompts.json`, and `route.json` whenever those stages occurred. Do not copy variant ZIPs into the final directory or nest one ZIP inside another.
- Refuse to mix new output with prior numbered files by default. Reuse an output directory only with an explicit `--overwrite`. Primary output scripts now start a recoverable directory transaction: the prior directory is moved to a same-parent backup, unrelated files are copied into the fresh output, and the backup is removed only on explicit commit. Exceptions roll back automatically; a dead process is recovered from its journal on the next invocation. An active process owns the journal and cannot be taken over.
- Treat `artifact-manifest.json` as the hash-lineage authority. `prepare_workflow.py` records approved inputs and task dependencies, routing adds config/capability/route records, execution adds the accepted video/result/ledger revision, and `process_emoji_grid.py --manifest` adds processed artifacts. `scripts/artifact_manifest.py verify --manifest <path>` must fail if a current artifact is missing or has a different SHA-256.
- Run the configured trial cell before full-pack encoding. The default is cell `01`, so the rule works for any non-empty layout, with a 1 MiB GIF target. For Grok, test both the full 6-second file and the 3-second derivative. A trial budget or encoded-frame failure must produce a report and stop; a pass authorizes processing the remaining cells from the same already-generated grid video, not another provider call. The full-pack command must present that exact successful `processing.json` via `--trial-report`; input, layout, settings, cell, and variant hashes are checked before encoding. In the full-pack run, later GIF budget overages are warnings and do not block delivery; encoded-frame failures remain blocking.

## 240px GIF 边缘质量

- 先区分问题发生在哪一步：源视频已有破碎轮廓，还是连续 Alpha 抠像损坏，还是只有二值透明 GIF 出现锯齿。保留同一动作、同一帧的源图、RGBA/无损 WebP 和 GIF 做对照，避免用换模型掩盖本地编码问题。
- 参考图生图采用绿幕时，主体若有绿色衣物或道具，去背后必须在浅、深底对照原图检查颜色与不透明度，尤其是衣服内部。固定色键视频只对已识别为色键的连通区域改透明度；它允许识别被主体包围的纯色洞，但不能因此把去绿范围扩到整张图。普通边界连通模式只允许窄边修正，遇到同色主体边缘仍须目视判断。GIF 阈值根据 Alpha 几何与时间稳定性选择，不能把可见绿色一概当作漏色。`normalize_static_sheet.py` 的静态图归一化也只处理色键边缘。若主体与底板颜色在像素上实质无法区分，算法不能可靠还原；能选底板时改用高对比色键，否则重新取得真实 Alpha 或重做素材。Grok 与其他视频输入都应在生成前由 `prepare_workflow.py` 选安全色键；已经用错误色键生成的源素材不能靠事后改色可靠修复，仍需目视复核。
- 用**最终编码的 GIF** 审片：把同一帧的源 RGBA/无损 WebP、透明 GIF 在浅色和深色背景上按实际 240×240 尺寸对照，再放大检查发梢、手指、腿和道具轮廓；抽查起始、动作峰值和结尾，留意边缘是否逐帧闪烁。文件规格通过不等于轮廓过关。
- GIF 只能指定透明色索引，没有连续半透明边缘。若源帧圆顺而透明 GIF 有毛刺，优先复用已生成的连续 Alpha 帧，在本地轻度清理孤立尖刺、平滑 Alpha 再量化；只在确认有逐帧轮廓抖动时做局部时间一致性修正，检查动作是否被拖影。不要全图模糊或强腐蚀，以免抹掉头发、手指或球，也不要用高频透明抖动换来新的噪点。保留原版，在相同源帧和设置下做本地 A/B，再复检 240×240、无限循环、动作和逐张大小；微信整套交付采用 `album_workflow.py pack` 的 500000 字节限制，而非 grid trial 的 1 MiB 门槛。边缘宽度、阈值和修边强度须按素材实测，不能把一套样片参数硬套所有主体。
- 背景模式以用户确认的整套计划为准。`transparent` 才运行色键与连续 Alpha 修边；可额外做浅底 A/B 样片，但不能混进透明底专辑。`opaque` 保留原生场景或指定底色，直接用 `scene_video_to_gif.py` 转为每帧完全不透明的 GIF，不做抠像、去绿边或 Alpha 阈值。浅底只是可选画面风格，不能由工具替用户擅自选择。`album_workflow.py pack` 按背景模式验收整套；封面和聊天图标仍需按它们自己的透明素材规则制作。
- 透明版经本地修边仍明显粗糙时，回到主体锚图和静态首帧，考虑简洁、闭合的扁平卡通轮廓及更少细碎发丝；这会改变视觉风格，应服从用户指定的写实或卡通方向。纯导出问题先本地修，不为修 GIF 边缘自动重新提交图像/视频生成；新增调用仍受原费用和重试授权约束。

## QC report

`processing.json` should record source size and native fps/frame count, measured duration, selected duration profile, output fps/size, production-settings path and hash, detected grid, full-frame alpha method, registration, recovered crossings, ambiguous merged frames, per-cell invalid native-frame numbers, selected source frames, bad-frame repair details, fixed-canvas transform, adaptive GIF threshold, file-budget result, encoded-output QC, warnings, and the exact output list. Warn when:

- layout confidence is below `0.75`;
- foreground touches a crop boundary;
- an isolated bad frame had to be replaced;
- full-duration sampling cannot select a safe frame for any configured output time bin;
- in explicitly requested short-loop mode, no clean requested-duration loop remains for a cell;
- alpha coverage changes sharply across frames;
- the alpha-weighted centroid moves more than the hold-jitter threshold during the nominal hold segment;
- first and last frames differ enough to cause a visible jump;
- a cell is empty or nearly full-frame foreground;
- an encoder cannot preserve alpha.

Decode the final WebP and GIF and run QC on every encoded frame before packaging. Also composite the first-frame PNGs onto a light checkerboard preview. Dark subjects can hide interior holes on black. Visual identity and whether a motion feels natural remain human review items. Do not report them as machine-proven.

## Prompt-only delivery

When no video or local image-processing capability is available, deliver `static-prompt.json`, `tile-plan.json`, `prompts.json`, `route.json`, and `prompt-only.json` with `generated_video: false`. Do not create placeholder media or claim that generation started.
