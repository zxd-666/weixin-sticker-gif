# 一次制作整套动态微信表情

此入口用于用户给出主体描述、参考图或已确认主体图，要求直接做成一套动态表情。`scripts/album_workflow.py` 只做本地规划与最终文件验收；图像和视频生成由当前可用模型及现有路由执行。

## 输入与主体

展示唯一主体锚图时，只请用户确认主体的身份、造型和风格；场景不属于主体确认范围，也不要求锚图中出现。用户已明确要场景/原背景/有底色，后续记录 `opaque`；明确要透明底/去背，记录 `transparent`。若最终 GIF 是否带背景仍无法判断，在主体确认后、制作动作首帧或视频前再确定。不要因为旧脚本默认绿幕而抠掉用户要的场景。中途改变已记录的输出模式须重建计划，原计划哈希绑定的视频授权不可沿用。

生成主体锚图时先尝试当前 Agent 可用的图像工具，保留用户指定的外观；锚图可用透明或简洁背景，勿把场景生成作为主体确认条件。需要透明底时优先真实 Alpha，不得把棋盘格或与主体同色的绿幕当 Alpha。主体明显是绿色时，参考图静帧的色键用高反差色（例如品红），`compile_static_prompt.py --key-color '#FF00FF'`，视频任务再由 `prepare_workflow.py` 对静帧选安全色键或传同一个 `--key-color`；每一步都检查主体衣物/毛发未被抠空。`opaque` 模式的场景可以在动作首帧已有，也可以在主体确认后由视频模型依场景提示词生成；这不是要求用户确认另一张“场景主体锚图”。若当前 Agent 可直接图生视频，优先同一 Agent 的图像和视频能力；否则再发现其他账号/模型并按费用确认选择。

记录主体类型（真人、虚构或未知）、可见特征、指定风格和 8–24 个不重复的聊天动作。未指定动作时使用脚本内的八个默认动作；不要把试做的单张当作整套成品。参考图只用作身份依据。先用图像生成模型**只产出一张**主体锚图，展示实际结果后立即停止，等待用户针对这张图明确确认。用户提供的参考照不算主体锚图；只有恢复同一任务时，才复用该任务已确认且哈希未变的锚图。新任务仍先生成一张。若不满意，只在用户要求重做后再产出下一张候选图，不能同时批量试风格。确认后运行 `subject_anchor.py --image <锚图> --output works/<角色>/subject-anchor-approval.json --confirmed-by-user`，再运行 `album_workflow.py bind-anchor --plan ... --image <锚图> --approval works/<角色>/subject-anchor-approval.json --output works/<角色>/album-anchor.json`。此后各批静态提示词必须以这张图为 `reference_image`；批量预检会核对锚图及批准记录的哈希，并核对每张静态提示词都引用同一锚图，避免每张表情重新发明角色。真人素材遵守对应视频模型的资格要求，Seedance 继续执行肖像资产检查。

运行 `album_workflow.py plan`，生成 `works/<角色>/album-plan.json`。清单记录固定编号、动作、每批静态图和预计调用次数，另外为横幅、封面、图标及成对赞赏图预留最多五次附加图像调用；用户明确不要赞赏图时按最多三次重新估价。默认每批最多 4 个动作；最后一批按实际数量生成，不补充占位表情。生成静态图时使用统一锚图、风格和主体比例，逐批检查，再裁成独立的 `static/01.png` 到 `static/NN.png`。若图像模型不能可靠输出某一批布局，就改为该批逐张生成，并更新实际调用次数与费用预估；不得声称仍只花一次调用。

```bash
python3 scripts/album_workflow.py plan --name '小黑猫' --subject-description '黑猫，黄眼睛' --subject-type fictional --style '2D 手绘' --background-mode transparent --output works/小黑猫/album-plan.json
```

## 调用费用与执行

当前 Agent 原生图生视频工具由 Agent 按编号顺序调用，逐张用 `execute_video_route.py --native-video` 验收和登记；先核对整套费用/额度与用户授权，失败时停止后续调用。`album_workflow.py preflight/authorize-batch/run` 目前只支持外部适配器，不能用它冒充原生工具批量执行。下文的批量预检、授权和 `run` 命令仅适用于外部适配器路线；原生路线沿用逐张任务、收据、质量闸门和最终打包。

`transparent` 分支沿用透明/色键首帧、色键视频和 `process_emoji_grid.py` 抠像。`opaque` 分支使用独立 1×1 动作首帧，可以是只有主体的透明/简洁背景图，也可以已有场景。若要视频模型创作场景，用 `prompt_compiler.py --background-mode opaque --scene-prompt '具体场景、光线和色调'`；每张可描述不同动作场景，但整套角色和视觉风格保持统一。若首帧本身透明，必须提供 `--scene-prompt`，并选已验证支持透明参考图及场景生成的模型；否则在主体确认后另做动作首帧，不修改已确认锚图。`prepare_workflow.py --background-mode opaque` 直接送原首帧，设置 `allow_key_background=false`、`require_alpha=false`，不制作色键输入。当前 `grok-build-local` 适配器仍强制纯色色键背景，因此场景任务不能选它；应选已验证可按提示词生成/保留背景的模型，不能暗中换成绿幕。生成后检查视频每帧确有自然连续的场景；模型做不到时，停止并换合适路线，不把空白背景当成已完成的场景。

生成 `opaque` 动作视频后，以 `scene_video_to_gif.py <视频.mp4> <final-gifs/NN.gif>` 直接编码完整画面：只做时间窗口选择、居中方裁、240×240 缩放、调色板量化和循环，不抠像、不去绿、不改 Alpha。默认保留完整时长；如动作首尾不闭合，可指定 `--start-seconds` 与 `--duration-seconds` 选择真实连续片段。这个脚本在 500KB 内尝试有限帧率/色数，仍超限就停下调整场景复杂度或动作窗口，不静默降低到卡顿帧率。透明底分支仍用原处理脚本，并只在这条分支做去绿边和 Alpha 边缘检查。两条分支都按最终 GIF 审查首尾跳帧、动作清晰度与画面质量；附加素材的封面和聊天图标仍按其各自透明度规则制作。

在第一次可能付费的图像或视频调用前，检查当前账号权益与价格来源，向用户呈现：主体图调用数、静态图调用数、最多五次附加素材图像调用数、视频调用数、所选模型、图像及视频分别估价、预计总费用和整套费用上限。费用未知或可能超出既有额度时停在本地计划，不提交生成。已有订阅额度也要核对可用量；登录不代表免费。用户确认整套预算后，按照同一清单执行，不逐张重复询问。图像调用的费用仍需在其第一次提交前核对；后续 `authorize-batch` 是视频批次的程序化费用闸门，不能拿它代替图像费用确认。任何更换模型、超过总上限、追加付费、失败后重试或超出清单的调用都重新确认。每个视频任务仍生成独立的 `connection.json`、`video-task.json`、`route.json` 和 hash 绑定的 `execution-approval.json`；调用前逐项用现有 `validate_execution` 检查。**不把一次授权解释为无限重试。**

每张表情用其独立静态首帧发起一次图生视频；每个视频工作区固定为 `video/01` … `video/NN`，1×1 布局。用户明确要求一键直接完成、且静态首帧已通过主体与画质检查时，可用 `manage_job_state.py create --source-type album-generated --album-plan ... --album-item NN --anchor-approval works/<角色>/subject-anchor-approval.json --direct-completion-authorized` 为每张建立绑定计划和图片哈希的状态，不逐张请求静图确认。若用户要求先看静图，仍用普通 `generated` 审批入口。然后用现有 `prepare_workflow.py`、`route_video_provider.py`、`configure_video.py authorize` 为每张准备任务和费用确认。`transparent` 模式的单次 Grok 请求保持经主体颜色检查的纯色色键背景、固定镜头、仅一个动作、无自动重试；`opaque` 模式在当前 Grok 适配器处阻断。全部任务准备完后，先运行 `album_workflow.py preflight --plan ... --job-root works/<角色>` 核对所有任务与逐次费用确认。向用户展示报告中的剩余调用数、预计视频额外费用、视频批次最高额外费用与币种；确认未超出之前的整套上限后，用 `authorize-batch --plan ... --job-root ... --max-total-cost ... --currency ... --confirmed-by-user --output works/<角色>/album-execution-approval.json` 绑定这批任务。现有订阅额度路线用 `--max-total-cost 0` 且不传 `--currency`。最后运行 `run --plan ... --job-root ... --batch-approval works/<角色>/album-execution-approval.json` 顺序提交。每张成功、失败和远端任务 ID 由既有执行器记录。任务失败时暂停后续付费调用。对已有提交但结果未知的任务只按远端 ID 查询，不能重新 POST。用户可以只对失败的编号授权新尝试。确认超过一小时有效期时停下并重新核对额度。

`album_workflow.py run` 只顺序生成并登记视频，不会自动导出 GIF。随后按 `video-result.json` 中成功收据的实际视频路径逐张处理：透明底用 `process_emoji_grid.py` 处理每段 1×1 视频；保留场景用 `scene_video_to_gif.py` 直接转换到 `final-gifs/NN.gif`，不运行色键 QC、抠像或透明 GIF 阈值选择。先核对收据与任务编号及视频文件，再选择能满足预算的真实连续动作窗口。每张输出必须是 240×240、无限循环、有动态帧、≤500000 字节的 GIF。全长视频若超限，只能在不捏造姿态的前提下本地裁切/压缩，并在报告里记录；未过关则整套保持“待修复”，不能把已有几张冒充成品。要逐张人工检查身份一致、动作可辨、彼此差异和首尾循环。

全部 GIF 通过后，不要立刻打包。先读 [附加素材与打包](album-submission-assets.md)，分别制作并检查详情页横幅、透明封面、透明聊天页图标，以及默认成对的赞赏引导图和赞赏致谢图。新增生图调用仍须遵守费用闸门。用户明确不要赞赏素材时才省略两张，并在素材验证及打包命令加 `--no-reward`。把验证通过的 GIF 按 `01.gif` … `NN.gif` 放入媒体目录，把附加素材放入独立目录，再运行：

```bash
python3 scripts/album_assets.py validate --directory works/角色/附加素材
python3 scripts/album_workflow.py pack --plan works/角色/album-plan.json --media-dir works/角色/final-gifs --asset-dir works/角色/附加素材 --output works/角色/交付
```

验收器会拒绝缺张、多张、超出 500000 字节、尺寸不对、非循环或实际静止的 GIF，也会拒绝缺失或不合格的横幅、封面、图标、赞赏图。GIF 交付名为画面对应且互不重复的 1–4 字中文主题；动作名不符合时用 `--names-file` 提供编号到主题名的映射。ZIP 使用中文专辑名，内部只放 `表情/` 下的 GIF 和附加素材；任务清单与 `validation.json` 留在 ZIP 旁供审计。这一关只证明文件规格。主体一致性、表情语义、辅助图画面质量和微信平台审核仍需人工及上传页验收，不能用本地打包通过代替。

## 与旧入口的关系

用户只要单张样片、提供现成九宫格视频，或明确选择整格视频路线时，继续走原来的 grid 流程。用户要求“成套”“一键”“批量图生视频”时，走本入口，并保留同一套的独立视频工作区。初次任务若缺少主体或参考，先确定主体；缺少动作且无明确偏好时使用默认 8 张。"一键"表示一次给出任务后由 Skill 编排全部本地步骤和已授权调用，不表示绕过费用确认或质量验收。
