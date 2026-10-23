# 动态专辑的附加素材与打包

本文件是 `weixin-sticker-gif` 的独立制作基线，按张张提供并用于本地专辑制作的微信素材要求整理。平台上传页可能更新，正式投稿前仍以当时页面为准。本 Skill 不依赖其他 Skill 的文件或脚本。

## 交付清单与命名

| 素材 | 数量与格式 | 尺寸 | 本地体积检查 |
| --- | --- | --- | --- |
| 动态表情主图 | 8–24 张 GIF，同套统一动态 | 240×240 | 每张 ≤500000 字节，按确认模式透明或保留场景、无限循环且有实际动态帧 |
| 详情页横幅 | 1 张 PNG 或 JPG | 750×400 | 大于 500KB 提示可能被平台压缩 |
| 表情封面 | 1 张透明 PNG | 240×240 | 大于 500KB 提示可能被平台压缩 |
| 聊天页图标 | 1 张透明 PNG | 50×50 | 严格小于 100KB |
| 赞赏引导图 | 默认 1 张 PNG、JPG 或单帧 GIF | 750×560 | 大于 500KB 提示可能被平台压缩 |
| 赞赏致谢图 | 默认 1 张 PNG、JPG 或单帧 GIF | 750×750 | 大于 500KB 提示可能被平台压缩 |

赞赏素材成对制作、校验和打包。用户明确表示不需要时，两张都不生成，并在验证与打包时使用 `--no-reward`；不要只交其中一张。体积的“平台可能压缩”是提示，不是本地硬拒绝；主 GIF 与聊天页图标仍按上表硬限制。

交付 ZIP 内仅放投稿图片。表情用画面对应的 **1–4 字中文主题名** 命名，名称互不重复；专辑名和 ZIP 名包含中文且不含英文字母、数字。素材文件和目录使用下列固定中文名称，不把技术报告装进投稿 ZIP：

```text
<中文专辑名>表情包.zip
├── 表情/
│   ├── 收到.gif
│   ├── 大笑.gif
│   └── …
├── 详情页横幅.png  （也可为 .jpg / .jpeg）
├── 表情封面.png
├── 聊天页图标.png
├── 赞赏引导图.png  （用户明确不需要时不出现）
└── 赞赏致谢图.png  （用户明确不需要时不出现）
```

工作区的独立视频/GIF 仍用 `01.gif`…`NN.gif` 追踪任务。`album_workflow.py pack` 根据计划动作名把它们映射为交付文件名；若动作名含 Emoji、数字或超过四个汉字，则提供 `--names-file`，内容是 `{"01":"收到","02":"大笑",...}`，编号须与计划完全一致。主题名只用于文件与清单；除非用户明确要求，画面不加字。

## 制作顺序

1. 先完成并审查全部动态 GIF。主体锚图已经按 [主体确认流程](full-album-workflow.md) 单张展示并获确认；附加素材沿用这张主体与同套画风。
2. 在新增图像模型调用前核对账号权益和额外费用。GIF 完成后分别制作附加素材的源图，避免把 50×50 图标机械缩小自封面。横幅应是与表情主题有关、有故事性的横构图，色彩与微信浅色界面有区分，**不放文字**，不使用白底或透明底；角色和道具不得拉伸。封面选辨识度高的正面半身或全身，透明底、少留白、不加白描边和非必要文字。图标单独构图为清晰的正面头部，透明底，缩到 50×50 后仍能辨认；不要白描边、白底、方框和直角。
3. 赞赏引导图与致谢图保持相同角色和画风，内容分别对应“邀请赞赏”和“感谢支持”。用户未指定文案时可纯画面；若有文字，逐字检查可读性和准确性。两张均不得与 GIF 主图身份漂移。
4. 用本 Skill 的 `album_assets.py prepare` 将各源图按原比例裁切或置于透明画布，输出固定中文文件名。封面和图标的源图必须已有真实透明像素；`prepare` 不会从不透明图片猜背景或自动抠图。若图像模型只返回均匀纯绿底，先用本 Skill 的 `normalize_static_sheet.py` 抠成真实 Alpha，检查边缘后再传给 `prepare`；棋盘格、渐变或无法确认的背景不能直接抠。裁切后逐张目视检查关键角色、道具和文字没有被截断。
5. 用 `album_assets.py validate` 检查五张附加素材（或明确不要赞赏时的三张），再用 `album_workflow.py pack` 核对全部 GIF、主题名、素材和 ZIP 完整性。机器检查不能证明角色像不像、横幅故事性、文字、边缘锯齿、留白、动作差异或微信审核通过；交付前在实际显示尺寸检查。

```bash
python3 scripts/normalize_static_sheet.py works/角色/源图/封面绿底.png works/角色/源图/封面.png --report works/角色/源图/封面抠图报告.json  # 仅在源图没有真实 Alpha 且纯绿底合格时
python3 scripts/album_assets.py prepare --role banner --source works/角色/源图/横幅.png --output works/角色/附加素材/详情页横幅.png
python3 scripts/album_assets.py prepare --role cover --source works/角色/源图/封面.png --output works/角色/附加素材/表情封面.png
python3 scripts/album_assets.py prepare --role icon --source works/角色/源图/图标.png --output works/角色/附加素材/聊天页图标.png
python3 scripts/album_assets.py prepare --role reward-guide --source works/角色/源图/引导.png --output works/角色/附加素材/赞赏引导图.png
python3 scripts/album_assets.py prepare --role reward-thanks --source works/角色/源图/致谢.png --output works/角色/附加素材/赞赏致谢图.png
python3 scripts/album_assets.py validate --directory works/角色/附加素材
python3 scripts/album_workflow.py pack --plan works/角色/album-plan.json --media-dir works/角色/final-gifs --asset-dir works/角色/附加素材 --output works/角色/交付
```

`pack` 在 `交付/专辑素材/` 留下与 ZIP 相同的图片目录，在 `交付/` 留下供本地审计的 `album-plan.json` 和 `validation.json`；这两份 JSON 不进入 ZIP。已有输出目录或 ZIP 时拒绝覆盖，应使用新交付路径。没有赞赏素材且用户已明确选择不要时，给 `validate` 和 `pack` 都加 `--no-reward`。

本基线没有为逐张缩略图规定单独的投稿文件；`01.png` 等 GIF 首帧不是缩略图。正式上传若页面要求缩略图或其他新增字段，先核对该页规格并补齐，再宣称可投稿。
