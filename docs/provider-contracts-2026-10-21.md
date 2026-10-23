# Official provider contracts — 2026-10-21

Scope: MiniMax H3 I2V; Wan3.0 I2V/R2V; Seedance 2.0/2.5 portrait restrictions. Repository baseline: `74746ddb2c9961bc329806404e9526f7e111a39f`. Checked public official documentation on 2026-10-21 (Asia/Shanghai). **Verified** below means documented, not tested against a provider. No provider API, generation, account probe, upload, or credential inspection was performed. JSON examples are reduced mock fixtures, not recorded responses.

## 1. MiniMax H3: V2, not legacy Hailuo V1

### Endpoints and request

| Region | Create | Poll |
| --- | --- | --- |
| China | `POST https://api.minimax.cn/v2/video_generation` | `GET https://api.minimax.cn/v2/query/video_generation/{task_id}` |
| International | `POST https://api.minimax.io/v2/video_generation` | `GET https://api.minimax.io/v2/query/video_generation/{task_id}` |

Verified in the official [China schema](https://platform.minimax.cn/docs/api-reference/video/generation/api/v2-video-generation.json) and [international create reference](https://platform.minimax.io/docs/api-reference/video-generation-v2-create). The old documentation hostname `platform.minimaxi.com` redirects to `platform.minimax.cn`. Current H3 documentation uses `api.minimax.cn`; continued support for the legacy API hostname `api.minimaxi.com` was **not verified**. Do not silently change region/key or fall back to V1.

Headers: `Authorization: Bearer <API_KEY>`; POST additionally `Content-Type: application/json`. Required body fields: `model`, `content`, `resolution`, integer `duration`. Models/specs:

| Model ID | Resolution strings | Duration, seconds |
| --- | --- | --- |
| `MiniMax-H3` | `768P`, `2K` | integers 4–15 |
| `MiniMax-H3-Max` | `480P`, `768P` | integers 5–15 |

`content` must contain a nonempty `{"type":"text","text":"…"}` (maximum 7,000 characters). First image: `{"type":"image_url","image_url":{"url":"…"},"role":"first_frame"}`; a single image with omitted role defaults to first frame. Add a second image with `role:"last_frame"` for first/last-frame generation. I2V always uses adaptive aspect ratio; another valid `ratio` is ignored. Source: [create reference](https://platform.minimax.io/docs/api-reference/video-generation-v2-create).

```json
{
  "model": "MiniMax-H3",
  "content": [
    {"type": "text", "text": "The character waves once."},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}, "role": "first_frame"}
  ],
  "resolution": "768P",
  "duration": 5,
  "ratio": "adaptive"
}
```

The data above is a **structural fixture**, not a valid PNG. Other documented roles are `reference_image`, `reference_video`, `reference_audio`; never mix these with `first_frame`/`last_frame`. R2V ratio options are `adaptive|21:9|16:9|4:3|1:1|3:4|9:16`. H3-Max optionally accepts `extra.prompt_expansion_mode=disabled|balanced|quality` (default `balanced`); do not send undeclared H3 options. **Documentation conflict:** the create page permits last-frame-only, but the nested `ContentItem.role` schema says last frame must pair with first frame. First-frame and paired-frame inputs are unambiguous; last-frame-only support remains unresolved. Sources: [create reference](https://platform.minimax.io/docs/api-reference/video-generation-v2-create), [OpenAPI schema](https://platform.minimax.io/docs/api-reference/video/generation/api/v2-video-generation.json).

### Images and local-file alternatives

- `content[].image_url.url` supports public URL, `data:image/<lowercase-format>;base64,<data>`, or `mm_file://{file_id}`. A local path/`file://` is not a documented provider input. [ContentItem schema](https://platform.minimax.io/docs/api-reference/video/generation/api/v2-video-generation.json)
- Images: JPG/JPEG/PNG/WEBP/HEIC/HEIF; ≤30 MB each; each side 256–5760 px; width/height 0.4–2.5. First/last ≤1 each; reference images ≤9. Request body ≤64 MB including Base64 expansion. [official guide](https://platform.minimax.io/docs/guides/video-generation)
- Native local upload: `POST https://api.minimax.cn/v1/files/upload` or `https://api.minimax.io/v1/files/upload`; Bearer auth, multipart fields `purpose=video_generation_input`, binary `file`. Let `requests` generate the multipart boundary. Response: `{"file":{"file_id":123},"base_resp":{"status_code":0,"status_msg":"success"}}`; check `base_resp.status_code`, then use `mm_file://123`. Files expire after 7 days; invalid inputs are rejected on upload. Sources: [China upload](https://platform.minimax.cn/docs/api-reference/file-management-upload.md), [international upload](https://platform.minimax.io/docs/api-reference/file-management-upload.md).

### Async results

Create HTTP 200: `{"task_id":"t1"}`. Poll uses Bearer auth and the same regional base. Inspect `task.status`: `queued|running|succeeded|failed|cancelled`. Poll roughly every 10 seconds; task lookup covers the last 7 days. Successful download URL is directly `task.content.url`; **no V1 file-ID exchange**. URL is time-limited; requery after expiry. [query reference](https://platform.minimax.io/docs/api-reference/video-generation-v2-query), [workflow](https://platform.minimax.io/docs/guides/video-generation).

```json
{"task":{"id":"t1","model":"MiniMax-H3","status":"succeeded","content":{"url":"https://example.com/out.mp4"},"duration":5,"resolution":"768P","ratio":"1:1","task_type":"generation","modality":"video","usage":{"total_seconds":5,"input_seconds":0,"output_seconds":5,"input_image_count":1}}}
```

```json
{"task":{"id":"t1","status":"failed","error":{"code":"1026","message":"video description contains sensitive content"}}}
```

HTTP request errors have a different envelope: `{"type":"error","error":{"type":"authorized_error","message":"… (1004)","http_code":"401"},"request_id":"r1"}`. Documented HTTP statuses include 400/401/402/422/429/500; 402 means insufficient balance. Preserve task `error.code/message` separately from HTTP error `error.type/message/http_code`. `content`/`usage` may be absent before success. [task/error schemas](https://platform.minimax.io/docs/api-reference/video/generation/api/v2-video-generation.json)

## 2. Wan3.0: workspace-scoped MaaS HTTP

Official API is marked **preview**, updated 2026-10-15. Model/key/endpoint must share region. [international API](https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference)

### Endpoints and request

| Region | Base URL |
| --- | --- |
| China, Beijing | `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com` |
| International, Singapore | `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com` |
| Other documented regions | Substitute `ap-northeast-1`, `eu-central-1`, `us-east-1`, or `cn-hongkong` in the same workspace-host pattern |

Append `POST /api/v1/services/aigc/video-generation/video-synthesis` to create; `GET /api/v1/tasks/{task_id}` to poll. `{WorkspaceId}` is the actual business workspace ID, not an API key. POST headers: Bearer auth, `Content-Type: application/json`, **`X-DashScope-Async: enable`**. Poll requires Bearer auth. These are the current Wan3-specific addresses; do not copy older Wan2.x shared-host defaults. [China API](https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference)

```json
{
  "model": "wan3.0-video",
  "input": {
    "prompt": "The character waves once.",
    "media": [{"type": "first_frame", "url": "https://example.com/frame.png"}]
  },
  "parameters": {"resolution": "720P", "ratio": "adaptive", "duration": 5, "audio": false}
}
```

Verified request rules:

| Field | Allowed / default |
| --- | --- |
| `model` | required; `wan3.0-video` or `wan3.0-video-prime` (faster, same modes) |
| `input` | required; at least one of `prompt` or `media` |
| `input.prompt` | ≤20,000 characters; excess truncated |
| `input.media[]` | objects with required `type`, `url`; **not** MiniMax `content[]` |
| I2V media | `first_frame` ≤1, `last_frame` ≤1 |
| R2V media | `reference_image` ≤10; `reference_video` ≤5 / total ≤15 s; `reference_audio` ≤5 / total ≤15 s |
| `parameters.resolution` | `480P|720P|1080P`; default `1080P` |
| `parameters.duration` | integer 2–30 without input video; default 5; `-1` auto; with video, total input-video seconds + output seconds ≤30 |
| `parameters.ratio` | `adaptive` default; `21:9|16:9|4:3|1:1|3:4|9:16` |
| Other optional parameters | `audio=true`, `prompt_extend=true`, `watermark=false`; `seed=-1` or 0–2147483647 |

First/last-frame mode and reference mode are mutually exclusive. Prompt references use type-specific ordering (“图1”, “视频1”, “音频1”). Audio toggle does not change price. Sources: [China API](https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference), [official usage guide](https://help.aliyun.com/zh/model-studio/wan3-video-generation-guide). File/web references exist but are outside this I2V/R2V adapter scope.

### Images and local upload

Image `url` accepts HTTP(S) or `data:{MIME_type};base64,{data}`. JPEG/JPG/PNG/BMP/WEBP; no transparent channel; each side 240–8000 px; aspect ratio ≤8:1; ≤20 MB. Videos: URL, MP4/MOV, each 1–15 s, ≥16 fps, each side 240–4096 px, ≤100 MB; audio: URL, WAV/MP3, each 1–15 s, ≤15 MB. No raw local path is documented. [international API](https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference)

**China temporary upload, documented alternative:**

1. `GET https://dashscope.aliyuncs.com/api/v1/uploads?action=getPolicy&model=wan3.0-video` (use the exact subsequent model); Bearer and JSON headers. Read response `data`.
2. Multipart POST to `data.upload_host`; form mapping: `OSSAccessKeyId ← oss_access_key_id`, `Signature ← signature`, `policy ← policy`, `x-oss-object-acl ← x_oss_object_acl`, `x-oss-forbid-overwrite ← x_oss_forbid_overwrite`, `key={upload_dir}/{filename}`, `success_action_status=200`, binary `file`. All source values come from `data`; success is HTTP 200.
3. Pass `oss://{key}` as media URL and add `X-DashScope-OssResourceResolve: enable` to generation POST. Files bind to model + main account and expire in 48 hours. Respect the stricter Wan image limit, not the generic upload limit. [official upload protocol](https://help.aliyun.com/zh/model-studio/get-temporary-file-url), [Wan3 China input forms](https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference).

**Unknown internationally:** the [international upload page](https://www.alibabacloud.com/help/en/model-studio/get-temporary-file-url) says this feature is Beijing-only, but shows `https://dashscope-intl.aliyuncs.com/api/v1/uploads`. The international Wan3 API lists HTTP(S)/Base64, without temporary OSS support. Prefer public URL/Base64 for international; do not advertise international temporary upload as verified. Public HTTPS URLs from owned OSS are a separate, documented production alternative.

### Async result fixtures

Create success / create rejection, respectively:

```json
{"request_id":"r1","output":{"task_id":"t1","task_status":"PENDING"}}
```

```json
{"request_id":"r1","code":"InvalidApiKey","message":"Invalid API-key provided."}
```

Poll success / asynchronous task failure / expired-or-unknown task:

```json
{"request_id":"r1","output":{"task_id":"t1","task_status":"SUCCEEDED","video_url":"https://example.com/out.mp4"},"usage":{"video_count":1,"duration":5.0,"input_video_duration":0.0,"output_video_duration":5.0,"fps":30,"SR":720,"ratio":"16:9"}}
```

```json
{"request_id":"r1","output":{"task_id":"t1","task_status":"FAILED","code":"InvalidParameter","message":"The two modes are mutually exclusive."}}
```

```json
{"request_id":"r1","output":{"task_id":"t1","task_status":"UNKNOWN"}}
```

States: `PENDING|RUNNING|SUCCEEDED|FAILED|CANCELED|UNKNOWN` (one L in `CANCELED`). Poll around 15 seconds; task ID and download URL each have documented 24-hour validity. Output MP4/H.264. Errors before task creation are top-level; generation failure errors are inside `output`. Optional timestamps: `submit_time`, `scheduled_time`, `end_time`; `orig_prompt` may be returned. `usage.duration` includes input-video + output-video seconds. [international result contract](https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference)

## 3. Seedance 2.0 / 2.5: authorized real-person assets

**Verified:** both families reject direct uploads of real-person-face reference images/videos. Having the subject's permission or encoding the photo as Base64 does not replace platform enrollment. The official paths are trusted original model outputs, preset virtual portraits, or enrolled/authorized real-person assets. Trusted outputs must be original Ark outputs under the same account from the preceding 30 days; do not assume an edited copy or another platform's output qualifies. [portrait guide](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=en)

For the real-person route, the receiving account must complete personal/enterprise verification; invite the subject through the platform QR flow, set authorization validity, and have the subject log in, complete real-person verification, upload their own media, and authorize the receiving account. Recipient accepts the assets. One asset group represents one person; new outfits are allowed but every uploaded asset undergoes identity consistency checks. Only enrolled, accepted, currently authorized assets are usable; a visible list entry alone does not prove usability. [official enrollment instructions](https://docs.volcengine.com/docs/ark/upload-real-person-portrait-assets?lang=zh)

Use each individual **asset ID**, not its group ID, in the corresponding `content.<modality>_url.url`:

```json
{"type":"image_url","image_url":{"url":"asset://<ASSET_ID>"},"role":"reference_image"}
```

Equivalent media fields: `video_url.url` + `role:"reference_video"`, `audio_url.url` + `role:"reference_audio"`. Prompt refers to “图片1/视频1/音频1”, not to the asset ID. Source: [portrait guide](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=en).

API-managed assets must finish preprocessing: `Status=Active` is usable; `Failed` is not. Official readonly query: `POST https://ark.cn-beijing.volcengineapi.com/?Action=GetAsset&Version=2024-01-01`, body `{"Id":"<ASSET_ID>","ProjectName":"default"}`. This uses **signed AccessKey authentication, not Ark Bearer API key**; HTTP 200 can still contain failed asset status and `Error.Code/Message`. Do not use it as a Bearer-key probe. [asset workflow](https://docs.volcengine.com/docs/ark/guide-preview?lang=zh), [GetAsset API](https://docs.volcengine.com/docs/ark/get-asset-api?lang=zh).

Model identification: `doubao-seedance-2-5-260628`; `doubao-seedance-2-0-260128`; `doubao-seedance-2-0-fast-260128`; `doubao-seedance-2-0-mini-260615`. China generation is `POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks`, poll `GET .../tasks/{task_id}`, Bearer auth; successful result uses `content.video_url`. Duration: 2.5 integers 4–30 or `-1`; 2.0 family integers 4–15 or `-1`. 2.5 I2V requires `ratio:"adaptive"`. **Do not infer one common resolution matrix:** current docs distinguish 2.5, standard 2.0 (including 4k), and fast/mini. This note verifies portrait handling, not the complete Seedance adapter contract. Sources: [2.5 model/spec guide](https://docs.volcengine.com/docs/ark/seedance-2-5?lang=en), [2.0 guide](https://docs.volcengine.com/docs/ark/seedance-2-0?lang=en), [task API](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh).

**Unknown:** international/BytePlus equivalent enrollment, its model availability/endpoints, account-specific asset validity, and any generic Bearer-only portrait enrollment endpoint. Do not transfer China Ark rules/IDs to an international service by assumption.

### Seedance implementation addendum: IDs, roles, and the pinned Node SDK

**Decision:** do **not** put `asset://…` in `generateVideo({prompt:{image:…}})` in this repository's pinned SDK. An explicitly selected **reference-generation** route can preserve the URI through `providerOptions.bytedance.referenceImages`; the current bytes-based I2V gateway must block real-person requests until that route is enabled. This is a source-level finding, not a live provider test.

| China Ark model | Verified current ID | Versionless alias |
| --- | --- | --- |
| Seedance 2.5 | `doubao-seedance-2-5-260628` | not verified / not documented in checked sources |
| Seedance 2.0 | `doubao-seedance-2-0-260128` | not verified / not documented in checked sources |
| Seedance 2.0 fast | `doubao-seedance-2-0-fast-260128` | not verified / not documented in checked sources |
| Seedance 2.0 mini | `doubao-seedance-2-0-mini-260615` | not verified / not documented in checked sources |

Use these literal versioned IDs; do not invent short aliases such as `seedance-2.5` or `doubao-seedance-2-5`. [official current model comparison](https://docs.volcengine.com/docs/ark/seedance-2-5?lang=zh)

Authorized portrait **reference** submission, China Ark:

```json
{
  "model": "doubao-seedance-2-5-260628",
  "content": [
    {"type": "text", "text": "图片1中的人物向镜头挥手。"},
    {"type": "image_url", "image_url": {"url": "asset://<ASSET_ID>"}, "role": "reference_image"}
  ],
  "service_tier": "default",
  "duration": 5,
  "resolution": "720p",
  "ratio": "adaptive",
  "generate_audio": false
}
```

Send this as JSON to the China task POST above with Bearer auth. The authorized-portrait guide directly demonstrates `asset://` with `reference_image`/`reference_video`/`reference_audio`. `service_tier` is top-level; omit it or use `default`. **`flex` is explicitly unsupported for both Seedance 2.0 and 2.5**, even if an SDK type accepts it. [portrait example](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=en), [task API service tiers](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh&redirect=1)

**First-frame qualification:** the general task API permits image asset URIs and separately defines `first_frame` (or no role for a single first image), paired `first_frame`/`last_frame`, and `reference_image`. These modes are mutually exclusive; 2.5 I2V requires adaptive ratio. However, no checked portrait-specific example explicitly guarantees an **authorized real-person** asset URI in the `first_frame` role. Therefore `reference_image` is directly demonstrated; authorized-portrait `first_frame` is **not separately verified**, not proven forbidden. Do not silently turn a strict first-frame request into reference generation: subject appearance reference does not guarantee the exact starting frame. [general image/role contract](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)

Pinned implementation evidence (`package.json`: `ai=7.0.79`, `@ai-sdk/bytedance=2.0.33`; packages were not installed in this checkout, so the exact tagged upstream sources were inspected):

- Core `normalizeImageData()` recognizes only string prefixes `http://` and `https://` as URL-backed inputs. Other strings except `data:` are decoded as Base64. Thus `prompt.image:"asset://…"` does **not** preserve an asset URI; a `URL` object is not handled by that function either. The same normalizer also processes unified frame/reference inputs, so those are not a verified URI workaround. [exact core source, ai@7.0.79](https://raw.githubusercontent.com/vercel/ai/ai%407.0.79/packages/ai/src/generate-video/generate-video.ts)
- ByteDance's provider-specific `referenceImages` is validated as an array of strings, then each value is copied directly to `content[].image_url.url` with `role:"reference_image"`. It bypasses the core prompt-image normalizer. `serviceTier` maps to `service_tier`; `generateAudio` to `generate_audio`. [exact option schema](https://raw.githubusercontent.com/vercel/ai/%40ai-sdk%2Fbytedance%402.0.33/packages/bytedance/src/bytedance-video-model-options.ts), [exact serializer](https://raw.githubusercontent.com/vercel/ai/%40ai-sdk%2Fbytedance%402.0.33/packages/bytedance/src/bytedance-video-model.ts)
- Consequently the verified serialization shape is `prompt: "…"` **with no `prompt.image`**, plus `providerOptions: {bytedance: {referenceImages: ["asset://<ASSET_ID>"], serviceTier: "default", generateAudio: false}}`. Select China base URL explicitly. No image bytes/data URI may be added alongside it; no `lastFrameImage` or other reference/frame combination unless independently authorized and validated. Source: [same tagged serializer](https://raw.githubusercontent.com/vercel/ai/%40ai-sdk%2Fbytedance%402.0.33/packages/bytedance/src/bytedance-video-model.ts).
- The SDK defaults to BytePlus international, and its typed suggestions include `dreamina-seedance-2-0-260128` / `dreamina-seedance-2-0-fast-260128`, plus arbitrary strings. These are **not aliases** for the China `doubao-*` IDs and do not establish current international 2.5 availability or portrait enrollment support. [tagged provider defaults](https://raw.githubusercontent.com/vercel/ai/%40ai-sdk%2Fbytedance%402.0.33/packages/bytedance/src/bytedance-provider.ts), [tagged model-ID type](https://raw.githubusercontent.com/vercel/ai/%40ai-sdk%2Fbytedance%402.0.33/packages/bytedance/src/bytedance-video-settings.ts)

Gate recommendation for the implementing agent: bind explicit subject type, approved source SHA256, and user-verified **individual platform asset ID** to the selected provider/account/region and intended mode. That hash is local provenance; it does not prove the remote asset's contents or platform `Active`/authorization state. Preserve “user verified” versus “API verified” as distinct evidence. Fail before network if the subject is real-person and the route still reads local bytes, passes `asset://` through `prompt.image`, uses unverified international enrollment, or requires unverified strict first-frame behavior. A reference route is eligible only after the URI-preserving path and its serialized-body mock checks are enabled. No provider code was executed during this investigation.

## 4. Safe, non-generative CLI probes

These are documented request candidates, **not executed here**. A successful metadata read proves only what that endpoint reports, not balance or generation entitlement.

| Provider | Official readonly candidate | Parse / boundary |
| --- | --- | --- |
| MiniMax China/international | `GET https://api.minimax.cn/v1/models` / `https://api.minimax.io/v1/models`; Bearer | `{"object":"list","data":[{"id":"…","object":"model","created":0,"owned_by":"minimax"}]}`. OpenAI-compatible model catalogue; do not require H3 to appear or claim absence means H3 unavailable. [China](https://platform.minimax.cn/docs/api-reference/models/openai/list-models.md), [international](https://platform.minimax.io/docs/api-reference/models/openai/list-models) |
| MiniMax H3 task access | `GET {regional_base}/v2/query/video_generation?page_num=1&page_size=1`; Bearer | `items[]`, `total`; read metadata only, avoid logging historical content URLs. More specific optional task-read probe. [List Tasks](https://platform.minimax.io/docs/api-reference/video-generation-v2-list) |
| Wan Beijing | `GET https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/models?model=wan3.0-video`; Bearer | `success`, `output.total`, `output.models[]`; entries include `model`, `inference_provider`, `prices[]`. [List models](https://www.alibabacloud.com/help/en/model-studio/list-models) |
| Wan Singapore | `GET https://dashscope-intl.aliyuncs.com/api/v1/models?model=wan3.0-video`; Bearer | **List host differs from the workspace generation host.** Same list schema. [List models](https://www.alibabacloud.com/help/en/model-studio/list-models) |
| Alibaba account balance | BSS `QueryAccountBalance`, signed AccessKey system | `AvailableAmount`, `AvailableCashAmount`, `Currency`; separate auth/permission from Model Studio Bearer keys. Do not manufacture a DashScope balance endpoint. [official balance API](https://help.aliyun.com/en/user-center/developer-reference/api-bssopenapi-2017-12-14-queryaccountbalance) |
| Seedance portrait asset | `GetAsset` described above | Readonly despite POST, but signed AccessKey + asset ID required; not a general key-validation endpoint. |

No dedicated universally applicable `validate-key`, HTTP dry-run generation, or Bearer-key balance endpoint was verified for these adapters. For CLI, report separate `configured`, `metadata_probe_passed`, `balance_unknown`, `generation_unverified` states. These names are implementation recommendations, not provider enums. Never use an invalid/small generation POST as an auth probe.

## 5. Pricing identification, without generation

Use a dated catalogue keyed by provider, billing site, region/deployment, exact model ID, output resolution, and billing unit; retain source URL. Published list price does not establish the user's discount, balance, quota, or access.

| MiniMax model / resolution | China CNY per output second | International USD per output second |
| --- | --- | --- |
| H3 / 768P | 0.50 | 0.08 |
| H3 / 2K | 0.80 | 0.13 |
| H3-Max / 480P | 0.33 | 0.05 |
| H3-Max / 768P | 0.50 | 0.08 |

H3 input images: first 5 free, then CNY 0.20 / USD 0.04 each; H3-Max: first 2 free, then CNY 0.50 / USD 0.074 each. Audio input free; video inputs billed separately by seconds and output resolution. H3 uses pay-as-you-go; Hailuo video resource packs do not cover H3. Sources: [China price table](https://platform.minimax.cn/docs/pricing/overview.md), [international price table](https://platform.minimax.io/docs/pricing/overview).

| Wan billing site / deployment | Model | 480P / 720P / 1080P, per second |
| --- | --- | --- |
| China site / Beijing | `wan3.0-video` | CNY 0.30 / 0.60 / 1.20 |
| China site / Beijing | `wan3.0-video-prime` | CNY 0.45 / 0.90 / 1.80 |
| International site / Singapore | `wan3.0-video` | USD 0.05 / 0.10 / 0.20, **list price** |
| International site / Singapore | `wan3.0-video-prime` | USD 0.068 / 0.14 / 0.28 |

China sources: [standard model pricing](https://help.aliyun.com/zh/model-studio/wan3-0-video), [Prime pricing](https://help.aliyun.com/zh/model-studio/wan3-0-video-prime). International source: [official pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing), which advertises a limited-time 30% discount for standard Wan3; applicability unverified. Wan meters **input-video + successful output-video seconds**; audio toggle does not reduce price. Do not label Singapore USD rates as universal worldwide rates. Official readonly `List models` also exposes `prices[]`, but no authenticated price lookup was performed.

Seedance enrollment is a platform asset workflow; this research did **not** verify a complete current video/asset-entitlement price matrix. Private-library guides reference an advanced creative entitlement package; availability/capacity are account-dependent. Mark these prices unknown rather than borrowing MiniMax/Wan rates. [official private asset guide](https://docs.volcengine.com/docs/ark/guide-preview?lang=zh)

## Implementation / mock-test checklist (recommendations)

- Assert exact regional host, path, Bearer header and provider-specific body structure; Wan also requires async header. Persist task ID immediately; never resubmit on a polling timeout.
- Cover pending/running, success URL, terminal failure, cancellation and unknown status; missing result URL on a declared success is a protocol error. Preserve raw provider error/request ID without keys or signed URLs in routine logs.
- Test MiniMax HTTP error vs task error vs upload `base_resp`; Wan top-level rejection vs `output.code/message`; case-sensitive `cancelled` vs `CANCELED`.
- Test duration/resolution model matrix, no mixed frame/reference roles, Base64 MIME envelope and body-size budget, upload ID/expiry, and Wan workspace requirement.
- Seedance real-person assets require `asset://` and usable authorization/status evidence. A local permission flag is not enrollment. Keep enrolment/auth/billing unknown states explicit.
- Runtime behavior, actual key validity, account/model enablement, balances/discounts, and platform upload acceptance remain **unverified** until separately authorized live checks.
