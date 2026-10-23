# weixin-sticker-gif

[中文说明](README.md) · [License](LICENSE)

An agent skill for making a complete animated WeChat sticker album from a subject description or reference image. It first generates **one subject image for approval**. After approval, it builds action stills, creates a separate image-to-video job for each sticker, converts each video to a looping GIF, checks the results, and packages the supporting submission artwork.

The skill can work with people, animals, plants, and objects. It keeps a requested scene background, or removes a background only when transparent stickers are requested. It prefers the active agent's image and video capabilities. Other provider routes require a check of account permissions, model eligibility, and any additional charges. An available adapter alone does not prove that generation is authorized or successful.

## Preview

These existing public GIFs are 240×240, looping, and each under 500,000 bytes. They come from an earlier nine-cell experiment and illustrate output appearance, **not a verified run of the current separate-video-per-sticker album route**. [Source manifest](docs/assets/recent-sticker-pack/manifest.json).

| Embarrassed | Got it | Let's go |
| :---: | :---: | :---: |
| <img src="docs/assets/recent-sticker-pack/fox-01.gif" width="180" alt="Looping embarrassed fox sticker"> | <img src="docs/assets/recent-sticker-pack/fox-05.gif" width="180" alt="Looping got-it fox sticker"> | <img src="docs/assets/recent-sticker-pack/fox-06.gif" width="180" alt="Looping let's-go fox sticker"> |

Private reference-based tests also produced two football samples and a locally validated eight-sticker daily-life album with supporting assets. Their media is not included in this public repository. Local validation does not imply WeChat platform approval.

## Quick start (Codex)

Install the complete skill (Python 3 and Node.js 22+ required):

```bash
mkdir -p "$HOME/.codex/skills"
git clone https://github.com/zxd-666/weixin-sticker-gif.git "$HOME/.codex/skills/weixin-sticker-gif"
cd "$HOME/.codex/skills/weixin-sticker-gif"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci --ignore-scripts
```

In a new Codex chat, ask `$weixin-sticker-gif: Make eight everyday animated WeChat stickers from my attached character. Show me one subject image first.` The first expected result is an image for approval; video generation and packaging follow only after the required checks. Other agents can install the complete repository using their own Skill mechanism.

## Workflow

1. Provide a subject or reference image, theme, and 8–24 expressions or actions. Smaller sample requests are also supported.
2. Check image generation availability and cost; generate **one** subject anchor and wait for approval.
3. Decide whether the final GIFs should be transparent or keep a scene. Create and inspect the action stills.
4. Check video generation permission and cost. Prefer the current agent's native video tool, or select a verified external route.
5. Generate one video per sticker, process the chosen background mode, and export looping 240×240 GIFs no larger than 500,000 bytes each.
6. Inspect consistency, motion, edges, and looping. After all GIFs pass, create a 750×400 banner, 240×240 cover, 50×50 icon, and by default a 750×560 / 750×750 reward-art pair. Validate and package a Chinese-named ZIP.

The [Chinese README](README.md#制作流程) contains the Mermaid diagram, a sample request, output tree, and current validation boundaries. The skill entry point is [SKILL.md](SKILL.md), with [full workflow](references/full-album-workflow.md) and [submission asset specifications](references/album-submission-assets.md).

## License

Source-available for noncommercial use. Original contributions and modifications are offered under [PolyForm Noncommercial 1.0.0](LICENSE); commercial use requires separate permission. Previously MIT-licensed portions retain their original rights and copyright notice in [LICENSE.upstream](LICENSE.upstream). This noncommercial restriction does not revoke those existing MIT rights. Rights in likenesses, trademarks, third-party models, and generated media may require separate permission. This project is not OSI open source because OSI open source permits commercial use.

## Contact

ZhangZhang Lab · [GitHub](https://github.com/zxd-666) · [Xiaohongshu](https://xhslink.cn/o/7DSli2Fl3Vb)
